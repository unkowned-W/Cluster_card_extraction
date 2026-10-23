"""Create evidence-limited crystal structure cards from CSD-exported CIFs."""
from __future__ import annotations

import csv
import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
METALS = set("Sc Ti V Cr Mn Fe Co Ni Cu Zn Y Zr Nb Mo Tc Ru Rh Pd Ag Cd Hf Ta W Re Os Ir Pt Au Hg La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu".split())
CELL = {key: "_cell_" + tag for key, tag in {"a": "length_a", "b": "length_b", "c": "length_c", "alpha": "angle_alpha", "beta": "angle_beta", "gamma": "angle_gamma", "volume": "volume", "Z": "formula_units_z"}.items()}
LEGACY_CCDC_BLOCKS = {
    "135620": "SMSSEPH", "135621": "SMSPHSE", "135622": "SM8P",
    "176451": "YBSEAN7", "176452": "YBSETEPH_C", "176453": "YB4SE6SP",
    "190276": "MARK1RED", "190277": "YB4S9SCF2",
    "646886": "1", "785797": "2",
}


def tokens(text):
    lines = iter(text.splitlines())
    for line in lines:
        if line.startswith(";"):
            content = [line[1:]]
            for following in lines:
                if following.startswith(";"):
                    break
                content.append(following)
            yield "\n".join(content).strip()
        else:
            position = 0
            while position < len(line):
                while position < len(line) and line[position].isspace():
                    position += 1
                if position == len(line) or line[position] == "#":
                    break
                if line[position] in "'\"":
                    quote = line[position]
                    start = position + 1
                    position = start
                    while position < len(line):
                        if line[position] == quote and (position + 1 == len(line) or line[position + 1].isspace()):
                            yield line[start:position]
                            position += 1
                            break
                        position += 1
                    else:
                        raise ValueError("No closing quotation")
                else:
                    start = position
                    while position < len(line) and not line[position].isspace():
                        position += 1
                    yield line[start:position]


def cif_blocks(path):
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    markers = list(re.finditer(r"(?im)^\s*data_(\S+)[^\S\n]*(?:\n|$)", text))
    return [(match[1].upper(), text[match.start():markers[index + 1].start() if index + 1 < len(markers) else len(text)])
            for index, match in enumerate(markers)]


def select_cif_block(path, number, named, paper_refs):
    blocks = cif_blocks(path)
    if not blocks:
        raise ValueError("CIF has no data block")
    deposited = []
    for name, body in blocks:
        archive = re.search(r'(?im)^_database_code_depnum_ccdc_archive\s+[\'"]?CCDC\s+(\d+)', body)
        if archive and archive[1] == number:
            deposited.append((name, body))
    if len(deposited) == 1:
        block_name, text = deposited[0]
    elif deposited:
        raise ValueError(f"CCDC {number} occurs in multiple data blocks")
    elif len(blocks) == 1:
        block_name, text = blocks[0]
    else:
        chosen = LEGACY_CCDC_BLOCKS.get(number)
        selected = [(name, body) for name, body in blocks if name == chosen]
        if len(selected) != 1:
            raise ValueError(f"CCDC {number} has no uniquely identified data block")
        block_name, text = selected[0]
    if named and named.upper() != block_name:
        raise ValueError(f"filename refcode {named} differs from CIF data block {block_name}")
    if re.fullmatch(r"[A-Z]{6}\d{0,2}", block_name) and block_name != "GLOBAL":
        code = block_name
        if paper_refs and code not in paper_refs and LEGACY_CCDC_BLOCKS.get(number) != block_name:
            raise ValueError(f"CIF refcode {code} disagrees with paper card {sorted(paper_refs)}")
        if paper_refs and code not in paper_refs:
            code = next(iter(paper_refs))
    elif len(paper_refs) == 1:
        code = next(iter(paper_refs))
    elif not paper_refs:
        code = f"CCDC_{number}"
    else:
        raise ValueError(f"CCDC {number} has multiple paper-card refcodes: {sorted(paper_refs)}")
    return code, block_name, text


def parse_cif(path, block_text=None):
    stream = list(tokens(block_text if block_text is not None else path.read_text(encoding="utf-8-sig", errors="replace")))
    scalars, loops, index = {}, [], 0
    while index < len(stream):
        token = stream[index]
        if token.lower() == "loop_":
            index += 1
            headers = []
            while index < len(stream) and stream[index].startswith("_"):
                headers.append(stream[index].lower())
                index += 1
            if not headers:
                raise ValueError("loop without headers")
            values = []
            while index < len(stream) and not (stream[index].startswith("_") or stream[index].lower() == "loop_" or stream[index].lower().startswith(("data_", "save_"))):
                values.append(stream[index])
                index += 1
            if len(values) % len(headers):
                raise ValueError(f"incomplete loop: {headers[0]}")
            loops.append([dict(zip(headers, values[offset:offset + len(headers)])) for offset in range(0, len(values), len(headers))])
        elif token.startswith("_"):
            if index + 1 >= len(stream):
                raise ValueError(f"missing value: {token}")
            scalars[token.lower()] = stream[index + 1]
            index += 2
        else:
            index += 1
    return scalars, loops


def value(item):
    return None if item in (None, ".", "?") else item


def coordinate(raw):
    if value(raw) is None:
        return None
    return float(re.sub(r"\([^)]*\)$", "", raw))


def cartesian(fractional, cell):
    a, b, c, alpha, beta, gamma = cell
    alpha, beta, gamma = (math.radians(angle) for angle in (alpha, beta, gamma))
    cosine_alpha, cosine_beta, cosine_gamma = map(math.cos, (alpha, beta, gamma))
    sine_gamma = math.sin(gamma)
    if abs(sine_gamma) < 1e-9:
        raise ValueError("degenerate unit cell")
    middle = (cosine_alpha - cosine_beta * cosine_gamma) / sine_gamma
    height = math.sqrt(max(0, 1 - cosine_beta ** 2 - middle ** 2))
    x, y, z = fractional
    return (a * x + b * cosine_gamma * y + c * cosine_beta * z,
            b * sine_gamma * y + c * middle * z, c * height * z)


def displacement(first, second, cell):
    if first is None or second is None or cell is None:
        return None
    delta = tuple(second[index] - first[index] for index in range(3))
    centers = tuple(-round(component) for component in delta)
    vectors = (cartesian(tuple(delta[index] + centers[index] + shift[index] for index in range(3)), cell)
               for shift in ((x, y, z) for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1)))
    return min(vectors, key=lambda vector: sum(component ** 2 for component in vector))


def norm(vector):
    return math.sqrt(sum(component ** 2 for component in vector))


def shape_from_points(points):
    if len(points) < 3:
        return "insufficient metal sites for a 3D shape classification"
    centroid = [sum(point[axis] for point in points) / len(points) for axis in range(3)]
    matrix = [[sum((point[row] - centroid[row]) * (point[column] - centroid[column])
                   for point in points) for column in range(3)] for row in range(3)]
    for _ in range(30):
        row, column = max(((0, 1), (0, 2), (1, 2)), key=lambda pair: abs(matrix[pair[0]][pair[1]]))
        if abs(matrix[row][column]) < 1e-10:
            break
        angle = math.atan2(2 * matrix[row][column], matrix[column][column] - matrix[row][row]) / 2
        cosine, sine = math.cos(angle), math.sin(angle)
        rotation = [[float(axis == other) for other in range(3)] for axis in range(3)]
        rotation[row][row] = rotation[column][column] = cosine
        rotation[row][column], rotation[column][row] = sine, -sine
        matrix = [[sum(rotation[left][row] * matrix[left][right] * rotation[right][column]
                       for left in range(3) for right in range(3)) for column in range(3)] for row in range(3)]
    axes = sorted((max(0, matrix[index][index]) for index in range(3)), reverse=True)
    if axes[0] < 1e-9:
        return "coincident metal sites"
    if axes[1] / axes[0] < 0.06:
        return "approximately linear metal-site arrangement"
    if axes[2] / axes[0] < 0.06:
        return "approximately planar metal-site arrangement"
    return "three-dimensional metal-site arrangement"


def metal_framework(atoms, bonds, metal_sites, elements, scalars):
    positions = {}
    for atom in atoms:
        try:
            position = tuple(coordinate(atom[f"_atom_site_fract_{axis}"]) for axis in "xyz")
            if None not in position:
                positions[atom["_atom_site_label"]] = position
        except (KeyError, ValueError, TypeError):
            continue
    try:
        cell = tuple(coordinate(scalars[f"_cell_length_{axis}"]) for axis in "abc") + tuple(
            coordinate(scalars[f"_cell_angle_{axis}"]) for axis in ("alpha", "beta", "gamma"))
        if any(item is None for item in cell):
            cell = None
    except (KeyError, ValueError, TypeError):
        cell = None
    oxygen_to_metals = defaultdict(set)
    omitted = 0
    for bond in bonds:
        first, second = bond["_geom_bond_atom_site_label_1"], bond["_geom_bond_atom_site_label_2"]
        if first in metal_sites and elements.get(second) == "O":
            metal, oxygen = first, second
        elif second in metal_sites and elements.get(first) == "O":
            metal, oxygen = second, first
        else:
            continue
        symmetries = (bond.get("_geom_bond_site_symmetry_1", "1_555"),
                      bond.get("_geom_bond_site_symmetry_2", "1_555"))
        if any(symmetry not in ("1_555", "1") for symmetry in symmetries):
            omitted += 1
            continue
        oxygen_to_metals[oxygen].add(metal)
    links = defaultdict(list)
    for oxygen, metals in oxygen_to_metals.items():
        for index, first in enumerate(sorted(metals)):
            for second in sorted(metals)[index + 1:]:
                links[(first, second)].append(oxygen)
    edges = []
    edge_vectors = {}
    for (first, second), bridges in sorted(links.items()):
        bridge_angles = []
        bridge_vectors = []
        for oxygen in bridges:
            first_vector = displacement(positions.get(oxygen), positions.get(first), cell)
            second_vector = displacement(positions.get(oxygen), positions.get(second), cell)
            if first_vector is None or second_vector is None or not norm(first_vector) or not norm(second_vector):
                continue
            bridge_vectors.append(tuple(second_vector[axis] - first_vector[axis] for axis in range(3)))
            cosine = sum(left * right for left, right in zip(first_vector, second_vector)) / (norm(first_vector) * norm(second_vector))
            bridge_angles.append({"oxygen": oxygen, "angle_deg": round(math.degrees(math.acos(max(-1, min(1, cosine)))), 2),
                                  "metal_oxygen_distances_angstrom": [round(norm(first_vector), 3), round(norm(second_vector), 3)]})
        consistent = bool(bridge_vectors) and all(
            norm(tuple(component - reference for component, reference in zip(vector, bridge_vectors[0]))) < 0.05
            for vector in bridge_vectors[1:])
        if consistent:
            edge_vectors[(first, second)] = bridge_vectors[0]
        edges.append({"metals": [first, second], "shared_oxygen_labels": sorted(bridges),
                      "metal_metal_separation_angstrom": round(norm(bridge_vectors[0]), 3) if consistent else None,
                      "bridge_geometry": bridge_angles,
                      "geometry_warning": "bridge images disagree; separation omitted" if bridge_vectors and not consistent else None})
    adjacency = {label: set() for label in metal_sites}
    for edge in edges:
        first, second = edge["metals"]
        adjacency[first].add(second)
        adjacency[second].add(first)
    components = []
    unseen = set(adjacency)
    while unseen:
        pending = [min(unseen)]
        component = set()
        while pending:
            label = pending.pop()
            if label in component:
                continue
            component.add(label)
            pending.extend(adjacency[label] - component)
        unseen -= component
        components.append(sorted(component))
    largest = max(components, key=len, default=[])
    edge_count = sum(set(edge["metals"]).issubset(largest) for edge in edges)
    if len(largest) < 2:
        topology = "no oxygen-bridged metal pairs established"
    elif edge_count == len(largest) - 1:
        topology = "branched tree" if any(len(adjacency[label]) > 2 for label in largest) else "chain"
    else:
        topology = "network with cycles"
    unwrapped = {}
    consistent_component = True
    if largest and all(label in positions and None not in positions[label] for label in largest) and cell:
        unwrapped[largest[0]] = (0.0, 0.0, 0.0)
        pending = [largest[0]]
        while pending:
            label = pending.pop()
            for neighbor in adjacency[label]:
                pair = tuple(sorted((label, neighbor)))
                vector = edge_vectors.get(pair)
                if vector is None:
                    consistent_component = False
                    continue
                direction = 1 if label == pair[0] else -1
                target = tuple(unwrapped[label][axis] + direction * vector[axis] for axis in range(3))
                if neighbor not in unwrapped:
                    unwrapped[neighbor] = target
                    pending.append(neighbor)
                elif norm(tuple(target[axis] - unwrapped[neighbor][axis] for axis in range(3))) > 0.05:
                    consistent_component = False
    points = [unwrapped[label] for label in largest if label in unwrapped]
    shape = (shape_from_points(points) if largest and bonds and consistent_component
             and len(points) == len(largest) and not omitted
             else "undetermined (missing bonds, symmetry links, or consistent periodic-image geometry)")
    return {"links": edges, "connected_components": components, "topology": topology,
            "approximate_shape": shape, "omitted_nonidentity_symmetry_bonds": omitted,
            "geometry_basis": "Shared oxygen in CIF bond table (identity symmetry only); M-O vectors use nearest periodic images, M-M separations use the same bridge images, and the metal-site shape uses bridge-connected unwrapped coordinates. M-M values are separations, not metal-metal bonds."}


def candidate_motifs(card, nuclearity):
    """Find tentative dense modules in an eligible oxygen-bridged metal graph."""
    framework = card["metal_framework"]
    labels = sorted(site["label"] for site in card["metal_sites"])
    result = {"status": "not_assessed", "nuclearity": nuclearity,
              "nuclearity_basis": "matched article compound material_class.nuclearity",
              "method": "agglomerative weighted modularity; edge weight = shared oxygen count"}
    if nuclearity is None or nuclearity <= 20:
        return result
    if nuclearity > 250:
        result.update(status="not_assessed", reason="graph exceeds the 250-site analysis limit")
        return result
    if any(site.get("occupancy") is not None and abs(site["occupancy"] - 1) > 0.01
           for site in card["metal_sites"]):
        result.update(status="insufficient_graph", reason="partially occupied metal sites")
        return result
    if not framework["links"] or framework["omitted_nonidentity_symmetry_bonds"]:
        result.update(status="insufficient_graph", reason="missing links or omitted symmetry bonds")
        return result
    if len(labels) != nuclearity or len(framework["connected_components"]) != 1:
        result.update(status="incomplete_molecular_graph",
                      reason=f"{len(labels)} metal sites in {len(framework['connected_components'])} components; expected {nuclearity} sites in one molecule")
        return result

    weights = defaultdict(dict)
    for edge in framework["links"]:
        first, second = edge["metals"]
        weight = len(edge["shared_oxygen_labels"])
        weights[first][second] = weight
        weights[second][first] = weight
    degrees = {label: sum(weights[label].values()) for label in labels}
    total_degree = sum(degrees.values())
    partitions = [{label} for label in labels]
    while len(partitions) > 1:
        best_gain, best_pair = 0, None
        for first_index, first_group in enumerate(partitions):
            first_degree = sum(degrees[label] for label in first_group)
            for second_index in range(first_index + 1, len(partitions)):
                second_group = partitions[second_index]
                between = sum(weights[label].get(neighbor, 0)
                              for label in first_group for neighbor in second_group)
                gain = between - first_degree * sum(degrees[label] for label in second_group) / total_degree
                if gain > best_gain + 1e-9:
                    best_gain, best_pair = gain, (first_index, second_index)
        if best_pair is None:
            break
        first_index, second_index = best_pair
        partitions[first_index].update(partitions.pop(second_index))
    partitions = sorted((sorted(group) for group in partitions), key=lambda group: group[0])
    if len(partitions) < 2 or any(len(group) < 2 for group in partitions):
        result.update(status="no_reliable_partition", reason="no nontrivial partition without single-metal modules")
        return result
    module_by_label = {label: index for index, group in enumerate(partitions, 1) for label in group}
    elements = {site["label"]: site["element"] for site in card["metal_sites"]}
    modules = []
    for index, group in enumerate(partitions, 1):
        group_set = set(group)
        modules.append({"id": f"M{index}", "metal_labels": group,
                        "metal_composition": dict(sorted(Counter(elements[label] for label in group).items())),
                        "internal_metal_pairs": sum(set(edge["metals"]) <= group_set for edge in framework["links"])})
    connections = defaultdict(lambda: {"metal_pairs": 0, "shared_oxygen_labels": set()})
    for edge in framework["links"]:
        first, second = edge["metals"]
        source, target = sorted((module_by_label[first], module_by_label[second]))
        if source != target:
            connection = connections[(source, target)]
            connection["metal_pairs"] += 1
            connection["shared_oxygen_labels"].update(edge["shared_oxygen_labels"])
    result.update(status="candidate", modules=modules,
                  inter_module_connections=[{"modules": [f"M{source}", f"M{target}"],
                                             "metal_pairs": connection["metal_pairs"],
                                             "shared_oxygen_labels": sorted(connection["shared_oxygen_labels"])}
                                            for (source, target), connection in sorted(connections.items())],
                  interpretation_limit="Algorithmic graph partition, not author-defined units or an assembly pathway. Check symmetry, disorder, bond completeness and article figures before interpreting motifs.")
    return result


def extract(path, refcode, ccdc, dois, block_text=None, block_name=None):
    scalars, loops = parse_cif(path, block_text)
    atoms = next((rows for rows in loops if rows and "_atom_site_label" in rows[0] and "_atom_site_type_symbol" in rows[0]), [])
    bonds = next((rows for rows in loops if rows and "_geom_bond_atom_site_label_1" in rows[0] and "_geom_bond_atom_site_label_2" in rows[0]), [])
    elements = {row["_atom_site_label"]: re.match(r"[A-Z][a-z]?", row["_atom_site_type_symbol"]).group() for row in atoms}
    metal_sites = {label: element for label, element in elements.items() if element in METALS}
    neighbors = defaultdict(set)
    for bond in bonds:
        first, second = bond["_geom_bond_atom_site_label_1"], bond["_geom_bond_atom_site_label_2"]
        if first in metal_sites and elements.get(second) == "O":
            neighbors[first].add((second, bond.get("_geom_bond_site_symmetry_2", "1_555")))
        if second in metal_sites and elements.get(first) == "O":
            neighbors[second].add((first, bond.get("_geom_bond_site_symmetry_1", "1_555")))
    setting = value(scalars.get("_space_group_crystal_system") or scalars.get("_symmetry_cell_setting"))
    group = value(scalars.get("_space_group_name_h-m_alt") or scalars.get("_symmetry_space_group_name_h-m"))
    formula = value(scalars.get("_chemical_formula_moiety") or scalars.get("_chemical_formula_sum"))
    occupancies = {}
    for atom in atoms:
        try:
            occupancies[atom["_atom_site_label"]] = coordinate(atom.get("_atom_site_occupancy"))
        except (ValueError, TypeError):
            occupancies[atom["_atom_site_label"]] = None
    sites = [{"label": label, "element": element, "occupancy": occupancies.get(label),
              "oxygen_coordination_number": len(neighbors[label]) if bonds else None,
              "oxygen_neighbor_labels": sorted({item[0] for item in neighbors[label]}) if bonds else []}
             for label, element in metal_sites.items()]
    framework = metal_framework(atoms, bonds, metal_sites, elements, scalars)
    description = (f"{refcode} crystallizes in the {setting} crystal system with space group {group}."
                   if setting and group else f"{refcode}: crystal system or space group not fully reported.")
    if formula:
        description += f" Reported CIF formula moiety: {formula}."
    if bonds and sites:
        description += " From the CIF bond table, " + "; ".join(
            f"{site['label']} ({site['element']}) has {site['oxygen_coordination_number']} O neighbors" for site in sites
        ) + "."
    else:
        description += " Metal?O coordination is not determined because atom sites or bond data are absent."
    if framework["links"]:
        distances = [edge["metal_metal_separation_angstrom"] for edge in framework["links"]
                     if edge["metal_metal_separation_angstrom"] is not None]
        angles = [angle["angle_deg"] for edge in framework["links"] for angle in edge["bridge_geometry"]]
        description += (f" Oxygen-bridged metal-site graph: {len(framework['links'])} pairs, "
                        f"{len(framework['connected_components'])} components; largest component is a {framework['topology']} "
                        f"with {framework['approximate_shape']}.")
        if distances:
            description += f" Computed bridged metal-metal separations span {min(distances):.3f}-{max(distances):.3f} Å (not direct metal-metal bonds)."
        if angles:
            description += f" Computed M-O-M angles span {min(angles):.2f}-{max(angles):.2f}°; individual values and O labels are in metal_framework.links."
    else:
        description += " Oxygen-bridged metal connectivity is not established from the available bond table."
    return {
        "refcode": refcode, "ccdc_number": ccdc, "dois": dois,
        "source_data_block": block_name,
        "source_cif": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "formula_moiety": formula, "crystal_system": setting, "space_group_hm": group,
        "international_tables_number": value(scalars.get("_space_group_it_number") or scalars.get("_symmetry_int_tables_number")),
        "unit_cell": {key: value(scalars.get(tag)) for key, tag in CELL.items()},
        "metal_sites": sites, "atom_sites_available": bool(atoms),
        "bond_table_available": bool(bonds), "metal_framework": framework, "description": description,
        "interpretation_limit": "Oxidation states, nuclearity, oxo/hydroxo bridging, core charge and ligand identities/counts require article/SI or manual verification; atom-site counts are asymmetric-unit counts, not molecular stoichiometry. Graph topology is limited to identity-symmetry bonds in the CIF table. Approximate shape is based only on bridge-unwrapped metal-site coordinates in the largest component; symmetry-related bonds or periodic structures require manual crystallographic review.",
    }


def catalog(path):
    mapping = defaultdict(lambda: {"ccdc": set(), "dois": set()})
    if not path.is_file():
        return mapping
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            for code in (row.get("refcode") or "").upper().split("|"):
                code = code.strip()
                if code:
                    mapping[code]["ccdc"].add((row.get("ccdc_number") or "").strip().removesuffix(".0"))
                    if row.get("doi", "").strip():
                        mapping[code]["dois"].add(row["doi"].strip())
    return mapping


def cif_identity(path):
    blocks = []
    with path.open(encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            match = re.match(r"^\s*data_(\S+)", line, re.IGNORECASE)
            if match:
                blocks.append(match[1].upper())
    refcodes = {block for block in blocks if re.fullmatch(r"[A-Z]{6}\d{0,2}", block)
                and block != "GLOBAL"}
    if len(refcodes) != 1 or len(blocks) > 2 or (len(blocks) == 2 and "GLOBAL" not in blocks):
        return None, f"CIF data blocks do not identify one unambiguous refcode: {', '.join(blocks)}"
    return refcodes.pop(), None


def paper_compounds(card_dir):
    by_doi = defaultdict(list)
    for path in Path(card_dir).glob("*.json"):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        doi = (card.get("doi") or "").lower()
        for compound in card.get("list_of_rare_earth_compounds", []):
            if isinstance(compound, dict):
                by_doi[doi].append(compound)
    return by_doi


def paper_identifiers(compounds):
    by_refcode, by_number = defaultdict(set), defaultdict(set)
    for doi, entries in compounds.items():
        if not doi:
            continue
        for entry in entries:
            for code in entry.get("ccdc_refcodes", []):
                if isinstance(code, str) and code.strip():
                    by_refcode[code.strip().upper()].add(doi)
            for number in entry.get("ccdc_numbers", []):
                if number is not None:
                    by_number[str(number).strip().removesuffix(".0")].add(doi)
    return by_refcode, by_number


def paper_refcodes_by_number(compounds):
    matches = defaultdict(list)
    for doi, entries in compounds.items():
        for entry in entries:
            refs = {str(code).strip().upper() for code in entry.get("ccdc_refcodes", []) if str(code).strip()}
            for number in entry.get("ccdc_numbers", []):
                matches[str(number).strip().removesuffix(".0")].append((doi, refs))
    return matches


def matching_dois(code, number, compounds, identifiers, records):
    by_refcode, by_number = identifiers
    candidates = by_refcode.get(code, set()) | by_number.get(number, set())
    matched = set()
    for doi in candidates:
        for entry in compounds[doi]:
            codes = {item.upper() for item in entry.get("ccdc_refcodes", []) if isinstance(item, str)}
            numbers = {str(item).strip().removesuffix(".0") for item in entry.get("ccdc_numbers", [])}
            if (code in codes and (not numbers or number in numbers)) or (number in numbers and not codes):
                matched.add(doi)
                break
    if len(matched) == 1:
        return sorted(matched)
    if matched or candidates:
        return []
    record = records.get(code)
    if record and number in record["ccdc"] and len(record["dois"]) == 1:
        return sorted(record["dois"])
    return []


def formula_annotations(formula, name):
    annotations = {"ligand_counts": [], "explicit_core_charges": [], "explicit_oxidation_states": []}
    if not formula:
        return annotations
    sources = [(formula, "article formula")]
    if (name or "").startswith("[") and name != formula:
        sources.append((name, "article compound name (structural notation)"))
    for text, source in sources:
        for match in re.finditer(r"\((\u03bc\d+-O|\u03bc\d+-OH|OAc|OiPr|NO3|OH|H2O|tea|Htea|Piv)\)(\d*)", text):
            annotations["ligand_counts"].append({"unit": match[1], "count": int(match[2] or "1"),
                                                  "basis": f"explicit grouped unit in {source}"})
        for match in re.finditer(r"\[[^\[\]]+\](\d+[+-])", text):
            annotations["explicit_core_charges"].append({"charge": match[1], "basis": source})
    for match in re.finditer(r"([A-Z][a-z]?)(?:\((III|II|IV|VI|V|I)\)|(III|II|IV|VI|V|I))(?=\d|\b)", name or ""):
        annotations["explicit_oxidation_states"].append({"element": match[1], "state": match[2] or match[3],
                                                         "basis": "article compound name"})
    return annotations


def article_evidence(card, compounds):
    matches = []
    for doi in card["dois"]:
        options = compounds.get(doi.lower(), [])
        exact = [item for item in options if card["refcode"] in item.get("ccdc_refcodes", [])]
        numbered = [item for item in options if card["ccdc_number"] in [str(number) for number in item.get("ccdc_numbers", [])]]
        candidates = exact or numbered
        if len(candidates) == 1:
            matches.append({"doi": doi, "formula": candidates[0].get("formula"),
                            "compound_name": candidates[0].get("compound_name"),
                            "match_basis": "refcode" if exact else "ccdc_number"})
    distinct = {(item["formula"], item["compound_name"]) for item in matches}
    if len(distinct) == 1:
        card["article_compound"] = matches[0]
        matched = next((item for item in compounds[matches[0]["doi"].lower()]
                        if item.get("formula") == matches[0]["formula"]
                        and item.get("compound_name") == matches[0]["compound_name"]), None)
        raw_nuclearity = (matched or {}).get("material_class", {}).get("nuclearity")
        try:
            nuclearity = int(raw_nuclearity)
        except (TypeError, ValueError):
            nuclearity = None
        card["candidate_structural_motifs"] = candidate_motifs(card, nuclearity)
        formula = matches[0]["formula"]
        if formula:
            card["description"] += f" Article card reports molecular formula {formula}."
        annotations = formula_annotations(formula, matches[0]["compound_name"])
        card["formula_annotations"] = annotations
        if annotations["ligand_counts"]:
            card["description"] += " Explicit grouped units in the article formula/name: " + ", ".join(
                f"{entry['count']} {entry['unit']} ({entry['basis']})" for entry in annotations["ligand_counts"]
            ) + "."
        if annotations["explicit_oxidation_states"]:
            card["description"] += " Article name explicitly identifies " + ", ".join(
                f"{entry['element']}({entry['state']})" for entry in annotations["explicit_oxidation_states"]
            ) + "."
        if annotations["explicit_core_charges"]:
            card["description"] += " Explicit bracketed charge: " + ", ".join(
                entry["charge"] for entry in annotations["explicit_core_charges"]
            ) + "."
        card["interpretation_limit"] += " Empirical formulas alone do not establish unique oxidation-state assignments or ligand connectivity; annotations above reproduce explicit structural notation only."
    elif matches:
        card["article_match_conflicts"] = matches
        card["candidate_structural_motifs"] = candidate_motifs(card, None)
    else:
        card["candidate_structural_motifs"] = candidate_motifs(card, None)
    return card


def run(cif_dir=ROOT / "CIFs", metadata=ROOT / "data/cluster_complex.csv",
        out_dir=ROOT / "data/cif_structure_cards", limit=None, overwrite=False, refcodes=None,
        ccdc_numbers=None,
        card_dir=ROOT / "data/extracted_cards", progress=None, preview=False):
    cif_dir, out_dir = Path(cif_dir), Path(out_dir)
    records = catalog(Path(metadata))
    compounds = paper_compounds(card_dir)
    identifiers = paper_identifiers(compounds)
    paper_numbers = paper_refcodes_by_number(compounds)
    results, selected, conflicts = [], {}, set()
    allowed = {code.upper() for code in refcodes} if refcodes is not None else None
    allowed_numbers = {str(number).strip().removesuffix(".0") for number in ccdc_numbers} if ccdc_numbers is not None else None
    paths = sorted(cif_dir.glob("*.cif"))
    if progress:
        progress("scan", 0, len(paths), None)
    for index, path in enumerate(paths, 1):
        if progress and (index % 250 == 0 or index == len(paths)):
            progress("scan", index, len(paths), path.name)
        match = re.fullmatch(r"(\d+)(?:_([A-Za-z]{6}\d{0,2}))?", path.stem)
        if not match:
            continue
        number, named = match.groups()
        try:
            code, problem = cif_identity(path)
        except OSError as exc:
            results.append({"file": path.name, "status": "failed", "detail": str(exc)})
            continue
        block_name = None
        if problem:
            paper_matches = paper_numbers.get(number, [])
            if len(paper_matches) != 1:
                results.append({"file": path.name, "status": "unmatched", "detail": f"{problem}; paper-card CCDC match is not unique"})
                continue
            try:
                code, block_name, _ = select_cif_block(path, number, named, paper_matches[0][1])
            except (OSError, ValueError) as exc:
                results.append({"file": path.name, "status": "unmatched", "detail": str(exc)})
                continue
        if named and named.upper() != code and block_name is None:
            results.append({"file": path.name, "status": "unmatched", "detail": f"filename refcode {named} differs from CIF {code}"})
            continue
        if (allowed is not None or allowed_numbers is not None) and not (
            (allowed is not None and code in allowed)
            or (allowed_numbers is not None and number in allowed_numbers)
        ):
            continue
        if code in conflicts:
            results.append({"file": path.name, "status": "unmatched", "detail": f"refcode {code} has conflicting CCDC numbers"})
        elif code in selected:
            previous_path, previous_number, _ = selected[code]
            if previous_number != number:
                results.append({"file": path.name, "status": "unmatched", "detail": f"refcode {code} conflicts with {previous_path.name}: CCDC {number} versus {previous_number}"})
                selected.pop(code)
                conflicts.add(code)
            elif named and not previous_path.stem.endswith("_" + code):
                selected[code] = (path, number, block_name)
        else:
            selected[code] = (path, number, block_name)
    if limit is not None and limit < 0:
        raise ValueError("limit must be nonnegative")
    items = list(selected.items())[:limit]
    if preview:
        for code, (path, number, _) in items:
            dest = out_dir / f"{code}.json"
            exists = dest.is_file() and dest.stat().st_size > 0
            results.append({
                "file": path.name,
                "refcode": code,
                "ccdc_number": number,
                "status": "would_skip" if exists and not overwrite else "preview",
                "detail": str(dest),
            })
        return results
    if progress:
        progress("extract", 0, len(items), None)
    for index, (code, (path, number, block_name)) in enumerate(items, 1):
        if progress and (index == 1 or index % 10 == 0 or index == len(items)):
            progress("extract", index, len(items), path.name)
        dest = out_dir / f"{code}.json"
        if dest.exists() and not overwrite:
            results.append({"file": path.name, "status": "skipped", "detail": str(dest)})
            continue
        try:
            dois = matching_dois(code, number, compounds, identifiers, records)
            block_text = None
            if block_name is not None:
                _, _, block_text = select_cif_block(path, number, None, paper_numbers[number][0][1])
            card = article_evidence(extract(path, code, number, dois, block_text, block_name), compounds)
            out_dir.mkdir(parents=True, exist_ok=True)
            temp = dest.with_suffix(".json.tmp")
            temp.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temp.replace(dest)
            results.append({"file": path.name, "status": "saved", "detail": str(dest)})
        except (OSError, ValueError, AttributeError) as exc:
            results.append({"file": path.name, "status": "failed", "detail": str(exc)})
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    for result in run(limit=args.limit, overwrite=args.overwrite):
        print(f"{result['status']}: {result['file']} - {result['detail']}")
