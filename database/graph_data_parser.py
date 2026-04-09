import re
import os


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
        if f.endswith("graph.txt") and os.path.isfile(os.path.join(graph_folder_path, f))
    )
    if not graph_file_candidates:
        raise FileNotFoundError(f"No graph.txt file found in: {graph_folder_path}")

    graph_file_name = graph_file_candidates[0]
    graph_file_path = os.path.join(graph_folder_path, graph_file_name)

    return graph_file_path

def remove_states_from_graph(graph_text):
    """Trim the raw graph text before the ``States`` section.

    BURT currently uses the transition-heavy prefix of the graph file at runtime and
    excludes the verbose ``States`` block from the stored graph text.
    """
    states_header_match = re.search(r"^States \(\d+\):\s*$", graph_text, re.MULTILINE)
    
    if not states_header_match:
        return graph_text

    return graph_text[:states_header_match.start()].rstrip()

def filter_graph(unfiltered_graph_text):
    """Apply the current runtime graph filtering policy to raw graph text."""
    graph_text_states_removed = remove_states_from_graph(unfiltered_graph_text)
    return graph_text_states_removed

def _build_screen_id_maps_from_text(full_content):
    """
    Build stable simplified screen-ID mappings from raw graph text.

    Screen hashes are converted to ``S1``, ``S2``, and so on based on the order in
    which they appear in the ``States`` section. Hashes that appear only in
    transitions are appended afterward so the mapping still covers the full graph.
    """

    # --- Step 1: Collect hashes and names from the 'States' section, preserving their order ---
    ordered_hashes_from_states = []
    states_screen_names_map = {}

    states_section_match = re.search(r'States \(\d+\):\n(.*)', full_content, re.DOTALL)

    if states_section_match:
        states_raw_text = states_section_match.group(1).strip()

        screen_start_matches = list(re.finditer(r'^[a-f0-9]{64},', states_raw_text, re.MULTILINE))

        for i, match in enumerate(screen_start_matches):
            start_pos = match.start()
            end_pos = screen_start_matches[i + 1].start() if i + 1 < len(screen_start_matches) else len(states_raw_text)

            block_content = states_raw_text[start_pos:end_pos].strip()

            if not block_content:
                continue

            screen_header_match = re.match(r'^[a-f0-9]{64},\s*([^,]+),', block_content)
            if screen_header_match:
                screen_hash = screen_header_match.group(0).split(',')[0].strip()
                screen_name = screen_header_match.group(1).strip()

                if screen_hash not in ordered_hashes_from_states:
                    ordered_hashes_from_states.append(screen_hash)
                    states_screen_names_map[screen_hash] = screen_name

    # --- Step 2: Add any unique hashes found ONLY in transitions ---
    all_unique_hashes_in_final_order = list(ordered_hashes_from_states)

    transition_blocks = re.findall(
        r'^[a-f0-9]{64}:\s*\(s:\s*([a-f0-9]+)\s*,\s*t:\s*([a-f0-9]+)\s*\):.*',
        full_content,
        re.MULTILINE,
    )
    for source_hash, target_hash in transition_blocks:
        if source_hash not in all_unique_hashes_in_final_order:
            all_unique_hashes_in_final_order.append(source_hash)
            if source_hash not in states_screen_names_map:
                states_screen_names_map[source_hash] = None
        if target_hash not in all_unique_hashes_in_final_order:
            all_unique_hashes_in_final_order.append(target_hash)
            if target_hash not in states_screen_names_map:
                states_screen_names_map[target_hash] = None

    # --- Step 3: Assign S IDs ---
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
        final_unique_screen_hashes_with_names[screen_hash] = states_screen_names_map.get(screen_hash)

    return screen_id_map, reverse_screen_id_map, final_unique_screen_hashes_with_names

def get_screens_with_information_from_text(graph_text):
    """
    Reads the 'States' section from raw graph text, re-assembles multi-line screen
    definitions into logical blocks, and returns each block with its original hash ID
    replaced by its simplified ID (S1, S2, etc.).

    Args:
        graph_text (str): Raw graph text content.

    Returns:
        tuple[list[str], dict[str, str], dict[str, str]]:
            A list of simplified screen blocks, a map from simplified ID to original
            screen hash, and the reverse map.
    """
    screen_id_map, reverse_screen_id_map, _ = _build_screen_id_maps_from_text(graph_text)

    full_screen_logical_blocks = []
    states_section_match = re.search(r'States \(\d+\):\n(.*)', graph_text, re.DOTALL)

    if states_section_match:
        states_raw_text = states_section_match.group(1).strip()

        screen_start_matches = list(re.finditer(r'^[a-f0-9]{64},', states_raw_text, re.MULTILINE))

        if not screen_start_matches:
            return [], screen_id_map, reverse_screen_id_map

        for i, match in enumerate(screen_start_matches):
            start_pos = match.start()
            end_pos = screen_start_matches[i + 1].start() if i + 1 < len(screen_start_matches) else len(states_raw_text)

            block_content = states_raw_text[start_pos:end_pos].strip()

            if not block_content:
                continue

            original_hash_match = re.match(r'^[a-f0-9]{64}', block_content)
            if not original_hash_match:
                continue

            original_hash = original_hash_match.group(0)
            simplified_id = reverse_screen_id_map.get(original_hash)

            if simplified_id:
                modified_block = re.sub(r'^[a-f0-9]{64}', simplified_id, block_content, 1)
                full_screen_logical_blocks.append(modified_block)

    full_screen_logical_blocks.sort(
        key=lambda x: int(x.split(':', 1)[0][1:]) if re.match(r'^S\d+:', x) else float('inf')
    )

    return full_screen_logical_blocks, screen_id_map, reverse_screen_id_map

def _build_screen_id_maps(graph_path):
    """Read a graph file from disk and build its simplified screen-ID mappings."""
    with open(graph_path, 'r', encoding='utf-8') as f:
        full_content = f.read()

    return _build_screen_id_maps_from_text(full_content)

def get_screens_with_information(graph_path):
    """
    Reads the 'States' section from the graph file, re-assembles multi-line screen definitions
    into logical blocks, and returns each block with its original hash ID replaced by
    its simplified ID (S1, S2, etc.).

    Args:
        graph_path (str): The path to the graph.txt file.

    Returns:
        list: A list of strings, where each string is a full logical screen detail block
              with the original hash ID replaced by its simplified ID.
    """
    try:
        with open(graph_path, 'r', encoding='utf-8') as f:
            full_content = f.read()
    except FileNotFoundError:
        print(f"Error: Graph file not found at {graph_path}")
        return [], {}, {}

    screens_with_information, screen_id_map, reverse_screen_id_map = get_screens_with_information_from_text(full_content)
    if not screens_with_information:
        print(f"Warning: No valid screen definitions found in States section of {graph_path}.")
    return screens_with_information, screen_id_map, reverse_screen_id_map

def get_transitions(graph_path):
    """Return simplified transitions plus lookup maps for one graph file.

    Transition hashes are converted to ``T#`` IDs and referenced screen hashes are
    converted to their corresponding ``S#`` IDs so downstream prompts can work with
    shorter, more readable identifiers.
    """
    screen_id_map, reverse_screen_id_map, _ = _build_screen_id_maps(graph_path)

    transition_id_map = {}
    reverse_transition_id_map = {}
    simplified_transitions = []
    transition_counter = 1

    with open(graph_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    inside_transition_block = False
    for line in lines:
        line = line.strip()
        if line.startswith("Transitions"):
            inside_transition_block = True
            continue
        if line.startswith("States"):
            break

        if inside_transition_block and re.match(r'^[a-f0-9]{64}:', line):
            parts = line.split(":", 1)
            if len(parts) != 2:
                continue

            transition_hash = parts[0].strip()

            s_match = re.search(r'\(s:\s*([a-f0-9]+)\s*,\s*t:\s*([a-f0-9]+)\s*\)', parts[1])
            if not s_match:
                continue

            source_hash = s_match.group(1)
            target_hash = s_match.group(2)

            if transition_hash not in reverse_transition_id_map:
                tid = f"T{transition_counter}"
                reverse_transition_id_map[transition_hash] = tid
                transition_id_map[tid] = transition_hash
                transition_counter += 1

            # Use already assigned sorted S IDs
            simplified_source_id = reverse_screen_id_map.get(source_hash, source_hash)
            simplified_target_id = reverse_screen_id_map.get(target_hash, target_hash)

            remaining = re.sub(r'^[a-f0-9]{64}:\s*\(s:\s*[a-f0-9]+\s*,\s*t:\s*[a-f0-9]+\s*\):', '', line).strip()
            new_line = f"{reverse_transition_id_map[transition_hash]}: (s:{simplified_source_id},t:{simplified_target_id}): {remaining}"
            simplified_transitions.append(new_line)

    return simplified_transitions, transition_id_map, reverse_transition_id_map, screen_id_map, reverse_screen_id_map

def clean_transitions(transitions_list):
    """
    Cleans a list of transition strings by removing all information
    starting from the "weight=" keyword to the end of the string.

    Args:
        transitions_list (list): A list of transition strings, typically
                                 in the format "T#: (s:S#,t:S#): [...] weight=...".

    Returns:
        list: A new list of cleaned transition strings.
    """
    cleaned_list = []
    # Regex to match ' weight=' and everything that follows it (non-greedy .*?)
    # and then greedy .* to match till the end of the line.
    # The '?' after .* makes the matching non-greedy for the text before 'weight=',
    # ensuring we cut exactly from the *first* occurrence of ' weight='.
    # Actually, a simpler regex `r' weight=.*'` should work perfectly because we want
    # to remove everything *after* ' weight='.
    pattern = re.compile(r'\s*weight=.*')

    for transition_str in transitions_list:
        # Substitute the matched pattern with an empty string
        cleaned_str = pattern.sub('', transition_str)
        cleaned_list.append(cleaned_str.strip()) # .strip() to remove any leftover whitespace

    return cleaned_list

def get_screens(graph_path):
    """Return a newline-delimited list of simplified screen IDs and names."""
    screen_id_map, reverse_screen_id_map, unique_screen_hashes = _build_screen_id_maps(graph_path)

    screen_names_output = []

    # Create a list of (numerical_id, formatted_string) for sorting
    for screen_hash, screen_name_from_states in unique_screen_hashes.items():
        simplified_id = reverse_screen_id_map.get(screen_hash)
        if simplified_id:
            # Use the name found in the states block, or fallback if not found
            display_name = screen_name_from_states if screen_name_from_states is not None else "Unknown Screen"
            screen_names_output.append((int(simplified_id[1:]), f"{simplified_id}: {display_name}"))

    # Sort by the numerical part of the simplified ID (S1, S2, S3...)
    screen_names_output.sort(key=lambda x: x[0])

    return "\n".join([item[1] for item in screen_names_output])

def get_original_transition_ids(text, transition_id_map):
    """
    Replace simplified transition references with original transition hashes.

    The matcher accepts several shorthand reference styles and normalizes them to
    ``<original_id>`` form in the returned text.
    """

    # Normalize mapping keys to uppercase (T# form)
    normalized_map = {k.strip().upper(): v for k, v in transition_id_map.items()}

    def replacer(match):
        tid = (
            match.group(1) or match.group(2) or match.group(3) or match.group(4) or
            match.group(5) or match.group(6) or match.group(7)
        )
        tid = tid.strip().upper()

        if tid.isdigit():  # numeric-only → T#
            tid = f"T{tid}"

        original_id = normalized_map.get(tid, tid)
        return f"<{original_id}>"

    pattern = re.compile(
        r"<\s*T?(\d+)\s*>\s*$"                                  # <1>, <T1>, <0>
        r"|\(\s*T?(\d+)\s*\)\s*$"                               # (1), (T1), (0)
        r"|\[\s*T?(\d+)\s*\]\s*$"                               # [1], [T1]
        r"|[\(<\[]?\s*transition_id\s*[:=\-]\s*T?\s*(\d+)\s*[\)> \]]?\s*$"  # transition_id=23 / :T46 / -7
        r"|\(?\s*transition\s+T?(\d+)\s*\)?\s*$"                # (transition T1), <transition T2>
        r"|^Transition[: ]\s*T?(\d+)\s*$"                       # Transition: T11, Transition T11
        r"|^T?(\d+)\s*$",                                       # bare T5 or t5
        re.IGNORECASE | re.MULTILINE
    )

    return pattern.sub(replacer, text)

def get_simplified_transition_ids(text, reverse_transition_id_map):
    """
    Replace original transition hashes with simplified ``T#`` identifiers.

    Args:
        text (str): input text containing <hash> IDs
        reverse_transition_id_map (dict): {hash: T#}

    Returns:
        str: text with <hash> replaced by <T#>
    """

    def replacer(match):
        hash_id = match.group(1)
        tid = reverse_transition_id_map.get(hash_id, hash_id)  # fallback to hash if not mapped
        return f"<{tid}>"

    return re.sub(r"<([a-fA-F0-9]{64})>", replacer, text)

def get_extracted_transitions(simplified_transitions):
    """
    Extract human-readable transition summaries from simplified transition lines.

    Args:
        simplified_transitions (list): A list of strings, where each string is
                                       a simplified transition in the format:
                                       "T_id: (s:S_id,t:S_id): [id=..., act=(...) click, cp=[...], ...]"

    Returns:
        list: A list of newly formatted strings with extracted details.
              Example: "T3: (s:S3,t:S4): Action = click; Component = [Type = Button, Identifier = permission_allow_button, Text = Allow, Description = ""]"
    """
    formatted_transitions = []

    for transition_str in simplified_transitions:
        # 1. Extract the initial part: T_id: (s:S_id,t:S_id):
        # This regex captures the 'T#: (s:S#,t:S#):' part and the rest of the string
        header_match = re.match(r'^(T\d+:\s*\(s:S\d+,t:S\d+\)):(.*)', transition_str)
        if not header_match:
            # Skip lines that don't match the expected header format
            continue

        header_part = header_match.group(1).strip()
        details_part = header_match.group(2).strip()  # The part after the header

        # Initialize extracted values with blank strings for attributes that might be missing
        action = ""
        comp_type = ""
        comp_identifier = ""
        comp_text = ""
        comp_description = ""

        # 2. Extract Action (act)
        # Looks for 'act=(digit) ' followed by the action text (non-greedy, stopping at comma or end)
        action_match = re.search(r'act=\(\d+\)\s*([^,\]]+)', details_part)
        if action_match:
            action = action_match.group(1).strip()

        # 3. Extract Component (cp) and its sub-attributes
        # First, find the 'cp=' part. It can be 'cp=null' or 'cp=[...]'
        component_value_match = re.search(r'cp=(null|\[.*?\])', details_part)

        component_details_string = ""
        if component_value_match:
            raw_cp_value = component_value_match.group(1)
            if raw_cp_value.startswith('['):
                # If it's a bracketed component, remove the outer brackets
                component_details_string = raw_cp_value[1:-1].strip()
            # If raw_cp_value is 'null', component_details_string remains empty, which is desired

        if component_details_string:
            # Now parse the content within the component_details_string for specific attributes

            # Type (ty)
            type_match = re.search(r'ty=([^,\]]+)', component_details_string)
            if type_match:
                comp_type = type_match.group(1).strip()

            # Identifier (idx)
            identifier_match = re.search(r'idx=([^,\]]+)', component_details_string)
            if identifier_match:
                comp_identifier = identifier_match.group(1).strip()

            # Text (tx) - often within the component payload
            text_match = re.search(r'tx=([^,\]]+)', component_details_string)
            if text_match:
                comp_text = text_match.group(1).strip()

            # Description (dsc) - often at the end, so it might not be followed by a comma
            # Using [^\]]* to allow empty description and match till the end of the component string
            description_match = re.search(r'dsc=([^\]]*)', component_details_string)
            if description_match:
                comp_description = description_match.group(1).strip()

        # 4. Format the extracted information into the desired output string
        formatted_line = (
            f"{header_part}: Action = \"{action}\"; "
            f"Component = [Type = \"{comp_type}\", Identifier = \"{comp_identifier}\", "
            f"Text = \"{comp_text}\", Description = \"{comp_description}\"]"
        )
        formatted_transitions.append(formatted_line)

    return formatted_transitions

def replace_simplified_screen_ids_with_original_ids(screen_descriptions_text, screen_id_map):
    """
    Replaces simplified screen IDs (S1, S2, etc.) in a text with their original
    hash/numeric IDs using the provided screen_id_map.

    Args:
        screen_descriptions_text (str): A string containing screen descriptions
                                        with simplified IDs (e.g., "S1 - Start state...").
        screen_id_map (dict): A dictionary mapping simplified screen IDs (e.g., "S1")
                              to their original hash or numeric IDs.

    Returns:
        str: The modified text with simplified screen IDs replaced by original IDs.
    """
    # To prevent issues where "S1" in "S10" is replaced first,
    # sort the simplified IDs in descending order of their numerical part.
    # This ensures "S10" is processed before "S1", "S11" before "S1", etc.
    # The keys of screen_id_map are already in the "S#" format.
    sorted_s_ids = sorted(screen_id_map.keys(), key=lambda s_id: int(s_id[1:]), reverse=True)

    modified_text = screen_descriptions_text
    for s_id in sorted_s_ids:
        original_id = screen_id_map.get(s_id)
        if original_id is not None:  # Use is not None to handle cases where original_id might be 0
            # Use word boundaries (\b) to ensure we replace only the full S ID.
            # re.escape() is used in case s_id contains characters special to regex (though "S#" is usually safe).
            pattern = r'\b' + re.escape(s_id) + r'\b'
            modified_text = re.sub(pattern, str(original_id), modified_text)

    return modified_text

def replace_original_screen_ids_with_simplified_ids(text_content, reverse_screen_id_map):
    """
    Replace original screen IDs in text with the corresponding simplified ``S#`` IDs.

    Args:
        text_content (str): The input text containing original screen IDs.
        reverse_screen_id_map (dict): Maps original screen IDs (hash/numeric strings) to simplified S# IDs.

    Returns:
        str: The modified text with original screen IDs replaced by simplified S# IDs.
    """
    modified_text = text_content

    # We only need to iterate through the screen ID map
    # Sort original screen IDs by length in descending order to avoid partial replacements.
    sorted_original_screen_ids = sorted(reverse_screen_id_map.keys(), key=lambda x: (len(x), x), reverse=True)

    for original_id in sorted_original_screen_ids:
        simplified_id = reverse_screen_id_map[original_id]

        # Use word boundaries (\b) and re.escape() for robust replacement.
        pattern = r'\b' + re.escape(original_id) + r'\b'

        # Perform the replacement.
        modified_text = re.sub(pattern, simplified_id, modified_text)

    return modified_text
