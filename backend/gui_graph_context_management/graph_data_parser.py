import re
import os

# Supports:
# 1. 64-char SHA-style hashes
# 2. Positive integer IDs
# 3. Negative integer IDs
GRAPH_ID_PATTERN = r'(?:[a-f0-9]{64}|-?\d+)'


def get_graph_file_path(data_folder_path, bug_id):
    """Return the first graph file found for a bug's graph-data folder.

    The on-disk dataset is expected to be organized as ``Bug<id>/<run_dir>/*graph.txt``.
    This helper resolves that structure and returns the first matching graph file.
    """
    bug_folder_path = os.path.join(data_folder_path, f"Bug{bug_id}")
    if not os.path.isdir(bug_folder_path):
        raise FileNotFoundError(f"Bug folder not found: {bug_folder_path}")

    graph_folder_candidates = sorted(
        name
        for name in os.listdir(bug_folder_path)
        if os.path.isdir(os.path.join(bug_folder_path, name))
    )

    if not graph_folder_candidates:
        raise FileNotFoundError(f"No graph subfolder found in: {bug_folder_path}")

    graph_folder_name = graph_folder_candidates[0]
    graph_folder_path = os.path.join(bug_folder_path, graph_folder_name)

    graph_file_candidates = sorted(
        f
        for f in os.listdir(graph_folder_path)
        if f.endswith("graph.txt")
        and os.path.isfile(os.path.join(graph_folder_path, f))
    )

    if not graph_file_candidates:
        raise FileNotFoundError(
            f"No graph.txt file found in: {graph_folder_path}"
        )

    graph_file_name = graph_file_candidates[0]
    graph_file_path = os.path.join(graph_folder_path, graph_file_name)

    return graph_file_path


def remove_states_from_graph(graph_text):
    """Trim the raw graph text before the ``States`` section."""

    states_header_match = re.search(
        r"^States \(\d+\):\s*$",
        graph_text,
        re.MULTILINE,
    )

    if not states_header_match:
        return graph_text

    return graph_text[:states_header_match.start()].rstrip()


def filter_graph(unfiltered_graph_text):
    """Apply the current runtime graph filtering policy."""

    graph_text_states_removed = remove_states_from_graph(
        unfiltered_graph_text
    )

    return graph_text_states_removed


def _build_screen_id_maps_from_text(full_content):
    """
    Build stable simplified screen-ID mappings from raw graph text.
    """

    ordered_hashes_from_states = []
    states_screen_names_map = {}

    states_section_match = re.search(
        r"States \(\d+\):\n(.*)",
        full_content,
        re.DOTALL,
    )

    if states_section_match:
        states_raw_text = states_section_match.group(1).strip()

        screen_start_matches = list(
            re.finditer(
                rf"^{GRAPH_ID_PATTERN},",
                states_raw_text,
                re.MULTILINE,
            )
        )

        for i, match in enumerate(screen_start_matches):

            start_pos = match.start()

            end_pos = (
                screen_start_matches[i + 1].start()
                if i + 1 < len(screen_start_matches)
                else len(states_raw_text)
            )

            block_content = states_raw_text[start_pos:end_pos].strip()

            if not block_content:
                continue

            screen_header_match = re.match(
                rf"^({GRAPH_ID_PATTERN}),\s*([^,]+),",
                block_content,
            )

            if screen_header_match:

                screen_hash = screen_header_match.group(1).strip()
                screen_name = screen_header_match.group(2).strip()

                if screen_hash not in ordered_hashes_from_states:
                    ordered_hashes_from_states.append(screen_hash)
                    states_screen_names_map[screen_hash] = screen_name

    all_unique_hashes_in_final_order = list(
        ordered_hashes_from_states
    )

    transition_blocks = re.findall(
        rf"^({GRAPH_ID_PATTERN}):\s*"
        rf"\(s:\s*({GRAPH_ID_PATTERN})\s*,\s*"
        rf"t:\s*({GRAPH_ID_PATTERN})\s*\):.*",
        full_content,
        re.MULTILINE,
    )

    for _, source_hash, target_hash in transition_blocks:

        if source_hash not in all_unique_hashes_in_final_order:
            all_unique_hashes_in_final_order.append(source_hash)

            if source_hash not in states_screen_names_map:
                states_screen_names_map[source_hash] = None

        if target_hash not in all_unique_hashes_in_final_order:
            all_unique_hashes_in_final_order.append(target_hash)

            if target_hash not in states_screen_names_map:
                states_screen_names_map[target_hash] = None

    screen_id_map = {}
    reverse_screen_id_map = {}

    screen_counter = 1

    for screen_hash in all_unique_hashes_in_final_order:

        sid = f"S{screen_counter}"

        reverse_screen_id_map[screen_hash] = sid
        screen_id_map[sid] = screen_hash

        screen_counter += 1

    final_unique_screen_hashes_with_names = {}

    for screen_hash in all_unique_hashes_in_final_order:
        final_unique_screen_hashes_with_names[screen_hash] = (
            states_screen_names_map.get(screen_hash)
        )

    return (
        screen_id_map,
        reverse_screen_id_map,
        final_unique_screen_hashes_with_names,
    )


def get_screens_with_information_from_text(graph_text):
    """
    Return screen blocks with simplified screen IDs.
    """

    (
        screen_id_map,
        reverse_screen_id_map,
        _,
    ) = _build_screen_id_maps_from_text(graph_text)

    full_screen_logical_blocks = []

    states_section_match = re.search(
        r"States \(\d+\):\n(.*)",
        graph_text,
        re.DOTALL,
    )

    if states_section_match:

        states_raw_text = states_section_match.group(1).strip()

        screen_start_matches = list(
            re.finditer(
                rf"^{GRAPH_ID_PATTERN},",
                states_raw_text,
                re.MULTILINE,
            )
        )

        if not screen_start_matches:
            return [], screen_id_map, reverse_screen_id_map

        for i, match in enumerate(screen_start_matches):

            start_pos = match.start()

            end_pos = (
                screen_start_matches[i + 1].start()
                if i + 1 < len(screen_start_matches)
                else len(states_raw_text)
            )

            block_content = states_raw_text[start_pos:end_pos].strip()

            if not block_content:
                continue

            original_hash_match = re.match(
                rf"^{GRAPH_ID_PATTERN}",
                block_content,
            )

            if not original_hash_match:
                continue

            original_hash = original_hash_match.group(0)

            simplified_id = reverse_screen_id_map.get(original_hash)

            if simplified_id:
                modified_block = re.sub(
                    rf"^{GRAPH_ID_PATTERN}",
                    simplified_id,
                    block_content,
                    1,
                )

                full_screen_logical_blocks.append(modified_block)

    full_screen_logical_blocks.sort(
        key=lambda x: (
            int(x.split(":", 1)[0][1:])
            if re.match(r"^S\d+:", x)
            else float("inf")
        )
    )

    return (
        full_screen_logical_blocks,
        screen_id_map,
        reverse_screen_id_map,
    )


def _build_screen_id_maps(graph_path):
    """Read graph file and build screen ID mappings."""

    with open(graph_path, "r", encoding="utf-8") as f:
        full_content = f.read()

    return _build_screen_id_maps_from_text(full_content)


def get_screens_with_information(graph_path):
    """
    Reads the states section and returns simplified screen blocks.
    """

    try:
        with open(graph_path, "r", encoding="utf-8") as f:
            full_content = f.read()

    except FileNotFoundError:

        print(f"Error: Graph file not found at {graph_path}")

        return [], {}, {}

    (
        screens_with_information,
        screen_id_map,
        reverse_screen_id_map,
    ) = get_screens_with_information_from_text(full_content)

    if not screens_with_information:
        print(
            f"Warning: No valid screen definitions found in "
            f"States section of {graph_path}."
        )

    return (
        screens_with_information,
        screen_id_map,
        reverse_screen_id_map,
    )


def get_transitions(graph_path):
    """
    Return simplified transitions plus lookup maps for one graph file.

    Supports:
    - SHA256-style IDs
    - positive integer IDs
    - negative integer IDs
    - empty lines between transitions
    """

    (
        screen_id_map,
        reverse_screen_id_map,
        _,
    ) = _build_screen_id_maps(graph_path)

    transition_id_map = {}
    reverse_transition_id_map = {}

    simplified_transitions = []

    transition_counter = 1

    with open(graph_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    inside_transition_block = False

    transition_line_pattern = re.compile(
        rf"^({GRAPH_ID_PATTERN}):\s*"
        rf"\(s:\s*({GRAPH_ID_PATTERN})\s*,\s*"
        rf"t:\s*({GRAPH_ID_PATTERN})\s*\):\s*(.*)$"
    )

    for raw_line in lines:

        line = raw_line.strip()

        # ---------------------------------------------------------
        # Skip empty lines safely
        # ---------------------------------------------------------
        if not line:
            continue

        # ---------------------------------------------------------
        # Detect transition section
        # ---------------------------------------------------------
        if line.startswith("Transitions"):
            inside_transition_block = True
            continue

        # ---------------------------------------------------------
        # Stop at states section
        # ---------------------------------------------------------
        if line.startswith("States"):
            break

        if not inside_transition_block:
            continue

        # ---------------------------------------------------------
        # Parse transition line
        # ---------------------------------------------------------
        match = transition_line_pattern.match(line)

        if not match:
            continue

        transition_hash = match.group(1)
        source_hash = match.group(2)
        target_hash = match.group(3)
        remaining = match.group(4).strip()

        # ---------------------------------------------------------
        # Create simplified transition ID
        # ---------------------------------------------------------
        if transition_hash not in reverse_transition_id_map:

            tid = f"T{transition_counter}"

            reverse_transition_id_map[transition_hash] = tid
            transition_id_map[tid] = transition_hash

            transition_counter += 1

        simplified_source_id = reverse_screen_id_map.get(
            source_hash,
            source_hash,
        )

        simplified_target_id = reverse_screen_id_map.get(
            target_hash,
            target_hash,
        )

        simplified_transition_id = reverse_transition_id_map[
            transition_hash
        ]

        new_line = (
            f"{simplified_transition_id}: "
            f"(s:{simplified_source_id},"
            f"t:{simplified_target_id}): "
            f"{remaining}"
        )

        simplified_transitions.append(new_line)

    print(simplified_transitions)
    return (
        simplified_transitions,
        transition_id_map,
        reverse_transition_id_map,
        screen_id_map,
        reverse_screen_id_map,
    )


def clean_transitions(transitions_list):
    """
    Remove everything from 'weight=' onward.
    """

    cleaned_list = []

    pattern = re.compile(r"\s*weight=.*")

    for transition_str in transitions_list:

        cleaned_str = pattern.sub("", transition_str)

        cleaned_list.append(cleaned_str.strip())

    return cleaned_list


def get_screens(graph_path):
    """
    Return newline-delimited simplified screen IDs and names.
    """

    (
        screen_id_map,
        reverse_screen_id_map,
        unique_screen_hashes,
    ) = _build_screen_id_maps(graph_path)

    screen_names_output = []

    for screen_hash, screen_name_from_states in (
        unique_screen_hashes.items()
    ):

        simplified_id = reverse_screen_id_map.get(screen_hash)

        if simplified_id:

            display_name = (
                screen_name_from_states
                if screen_name_from_states is not None
                else "Unknown Screen"
            )

            screen_names_output.append(
                (
                    int(simplified_id[1:]),
                    f"{simplified_id}: {display_name}",
                )
            )

    screen_names_output.sort(key=lambda x: x[0])

    return "\n".join([item[1] for item in screen_names_output])


def get_original_transition_ids(text, transition_id_map):
    """
    Replace simplified transition references with original IDs.
    """

    normalized_map = {
        k.strip().upper(): v
        for k, v in transition_id_map.items()
    }

    def replacer(match):

        tid = (
            match.group(1)
            or match.group(2)
            or match.group(3)
            or match.group(4)
            or match.group(5)
            or match.group(6)
            or match.group(7)
        )

        tid = tid.strip().upper()

        if tid.isdigit():
            tid = f"T{tid}"

        original_id = normalized_map.get(tid, tid)

        return f"<{original_id}>"

    pattern = re.compile(
        r"<\s*T?(\d+)\s*>\s*$"
        r"|\(\s*T?(\d+)\s*\)\s*$"
        r"|\[\s*T?(\d+)\s*\]\s*$"
        r"|[\(<\[]?\s*transition_id\s*[:=\-]\s*T?\s*(\d+)\s*[\)> \]]?\s*$"
        r"|\(?\s*transition\s+T?(\d+)\s*\)?\s*$"
        r"|^Transition[: ]\s*T?(\d+)\s*$"
        r"|^T?(\d+)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    return pattern.sub(replacer, text)


def get_simplified_transition_ids(
    text,
    reverse_transition_id_map,
):
    """
    Replace original transition IDs with simplified T# IDs.
    """

    def replacer(match):

        hash_id = match.group(1)

        tid = reverse_transition_id_map.get(
            hash_id,
            hash_id,
        )

        return f"<{tid}>"

    return re.sub(
        rf"<({GRAPH_ID_PATTERN})>",
        replacer,
        text,
    )


def get_extracted_transitions(simplified_transitions):
    """
    Extract human-readable transition summaries.
    """

    formatted_transitions = []

    for transition_str in simplified_transitions:

        header_match = re.match(
            r"^(T\d+:\s*\(s:S\d+,t:S\d+\)):(.*)",
            transition_str,
        )

        if not header_match:
            continue

        header_part = header_match.group(1).strip()

        details_part = header_match.group(2).strip()

        action = ""
        comp_type = ""
        comp_identifier = ""
        comp_text = ""
        comp_description = ""

        action_match = re.search(
            r"act=\(\d+\)\s*([^,\]]+)",
            details_part,
        )

        if action_match:
            action = action_match.group(1).strip()

        component_value_match = re.search(
            r"cp=(null|\[.*?\])",
            details_part,
        )

        component_details_string = ""

        if component_value_match:

            raw_cp_value = component_value_match.group(1)

            if raw_cp_value.startswith("["):
                component_details_string = (
                    raw_cp_value[1:-1].strip()
                )

        if component_details_string:

            type_match = re.search(
                r"ty=([^,\]]+)",
                component_details_string,
            )

            if type_match:
                comp_type = type_match.group(1).strip()

            identifier_match = re.search(
                r"idx=([^,\]]+)",
                component_details_string,
            )

            if identifier_match:
                comp_identifier = (
                    identifier_match.group(1).strip()
                )

            text_match = re.search(
                r"tx=([^,\]]+)",
                component_details_string,
            )

            if text_match:
                comp_text = text_match.group(1).strip()

            description_match = re.search(
                r"dsc=([^\]]*)",
                component_details_string,
            )

            if description_match:
                comp_description = (
                    description_match.group(1).strip()
                )

        formatted_line = (
            f'{header_part}: Action = "{action}"; '
            f'Component = [Type = "{comp_type}", '
            f'Identifier = "{comp_identifier}", '
            f'Text = "{comp_text}", '
            f'Description = "{comp_description}"]'
        )

        formatted_transitions.append(formatted_line)

    return formatted_transitions


def replace_simplified_screen_ids_with_original_ids(
    screen_descriptions_text,
    screen_id_map,
):
    """
    Replace S# IDs with original screen IDs.
    """

    sorted_s_ids = sorted(
        screen_id_map.keys(),
        key=lambda s_id: int(s_id[1:]),
        reverse=True,
    )

    modified_text = screen_descriptions_text

    for s_id in sorted_s_ids:

        original_id = screen_id_map.get(s_id)

        if original_id is not None:

            pattern = r"\b" + re.escape(s_id) + r"\b"

            modified_text = re.sub(
                pattern,
                str(original_id),
                modified_text,
            )

    return modified_text


def replace_original_screen_ids_with_simplified_ids(
    text_content,
    reverse_screen_id_map,
):
    """
    Replace original screen IDs with simplified S# IDs.
    """

    modified_text = text_content

    sorted_original_screen_ids = sorted(
        reverse_screen_id_map.keys(),
        key=lambda x: (len(x), x),
        reverse=True,
    )

    for original_id in sorted_original_screen_ids:

        simplified_id = reverse_screen_id_map[original_id]

        pattern = r"\b" + re.escape(original_id) + r"\b"

        modified_text = re.sub(
            pattern,
            simplified_id,
            modified_text,
        )

    return modified_text