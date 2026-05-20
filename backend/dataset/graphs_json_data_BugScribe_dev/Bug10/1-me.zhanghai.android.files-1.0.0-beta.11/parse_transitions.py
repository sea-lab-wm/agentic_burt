#!/usr/bin/env python3
"""
Parse state transition graph data and convert transitions to JSON format.

Usage:
    python parse_transitions.py <input_file> [output_file]
    
Example:
    python parse_transitions.py 1-org_mozilla_focus-7_0-graph.txt transitions.json
"""

import re
import json
import sys
from pathlib import Path


def parse_transitions(file_path: str) -> list[dict]:
    """
    Parse transitions from the graph file.
    
    Each transition line has the format:
    <transition_id>: (s:<source_id>,t:<target_id>): [id=<id>, ex=<ex>, sq=<sq>, act=(<code>) <action>, 
        cp=[, ty=<type>, idx=<idx>, idnx=<idnx>, tx=<text>, x=<x>, y=<y>, h=<h>, w=<w>, dsc=<desc>], 
        txt=<txt>, exp=<exp>, tr=<tr>] weight=<weight> ds=<ds> sc=<screenshot> ex=<ex>
    
    Args:
        file_path: Path to the graph file
        
    Returns:
        List of transition dictionaries
    """
    transitions = []
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the Transitions section
    transitions_match = re.search(r'Transitions \((\d+)\):', content)
    if not transitions_match:
        print("Warning: Could not find Transitions section")
        return transitions
    
    expected_count = int(transitions_match.group(1))
    print(f"Expected transitions: {expected_count}")
    
    # Find where States section begins (to limit our search)
    states_match = re.search(r'States \(\d+\):', content)
    transitions_section = content[transitions_match.end():states_match.start() if states_match else len(content)]
    
    # Use regex to find all transitions (handles multi-line cases)
    # Pattern: 64-char hex followed by source/target, then content until weight=...ex=N
    transition_pattern = re.compile(
        r'([a-f0-9]{64}):\s*'  # transition_id
        r'\(s:([a-f0-9]{64}),t:([a-f0-9]{64})\):\s*'  # source and target
        r'\[(.+?)\]\s*'  # bracket content (non-greedy)
        r'weight=([\d.]+)\s+'  # weight
        r'ds=(\w+)\s+'  # ds
        r'sc=(\S+)\s+'  # screenshot
        r'ex=(\d+)',  # ex flag
        re.DOTALL  # Allow . to match newlines
    )
    
    for match in transition_pattern.finditer(transitions_section):
        transition_id = match.group(1)
        source_id = match.group(2)
        target_id = match.group(3)
        bracket_content = match.group(4)
        weight = float(match.group(5))
        data_source = match.group(6)
        screenshot = match.group(7)
        ex_flag = int(match.group(8))
        
        # Normalize bracket content (replace newlines with spaces)
        bracket_content = ' '.join(bracket_content.split())
        
        # Parse id, ex, sq from bracket content
        id_match = re.search(r'id=([^,]*)', bracket_content)
        sq_match = re.search(r'sq=(\d+)', bracket_content)
        
        # Parse action
        act_match = re.search(r'act=\((\d+)\)\s*([^,]+)', bracket_content)
        
        transition = {
            "id": transition_id,
            "source": source_id,
            "target": target_id,
            "weight": weight,
            "data_source": data_source,
            "screenshot": screenshot if screenshot != "null" else None,
            "ex": ex_flag
        }
        
        if id_match:
            val = id_match.group(1).strip()
            transition["details_id"] = None if val == "null" else val
        
        if sq_match:
            transition["sequence"] = int(sq_match.group(1))
        
        if act_match:
            transition["action"] = {
                "code": int(act_match.group(1)),
                "name": act_match.group(2).strip()
            }
        
        # Parse component info if cp is not null
        # Look for: cp=[, ty=..., idx=..., idnx=..., tx=..., x=..., y=..., h=..., w=..., dsc=...]
        if 'cp=[,' in bracket_content:
            ty_match = re.search(r'ty=([^,]*)', bracket_content)
            idx_match = re.search(r'idx=([^,]*)', bracket_content)
            idnx_match = re.search(r'idnx=(\d+)', bracket_content)
            tx_match = re.search(r'tx=([^,]*),\s*x=', bracket_content)
            x_match = re.search(r',\s*x=(\d+)', bracket_content)
            y_match = re.search(r',\s*y=(\d+)', bracket_content)
            h_match = re.search(r',\s*h=(\d+)', bracket_content)
            w_match = re.search(r',\s*w=(\d+)', bracket_content)
            dsc_match = re.search(r'dsc=([^\]]*)\]', bracket_content)
            
            component = {}
            if ty_match:
                component["type"] = ty_match.group(1).strip()
            if idx_match:
                val = idx_match.group(1).strip()
                component["index"] = val if val else None
            if idnx_match:
                component["index_num"] = int(idnx_match.group(1))
            if tx_match:
                val = tx_match.group(1).strip()
                component["text"] = val if val else None
            if x_match and y_match and h_match and w_match:
                component["bounds"] = {
                    "x": int(x_match.group(1)),
                    "y": int(y_match.group(1)),
                    "height": int(h_match.group(1)),
                    "width": int(w_match.group(1))
                }
            if dsc_match:
                val = dsc_match.group(1).strip()
                component["description"] = val if val else None
            
            if component:
                transition["component"] = component
        
        transitions.append(transition)
    
    print(f"Parsed transitions: {len(transitions)}")
    return transitions


def parse_states(file_path: str) -> list[dict]:
    """
    Parse states from the graph file.
    
    Args:
        file_path: Path to the graph file
        
    Returns:
        List of state dictionaries
    """
    states = []
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the States section
    states_match = re.search(r'States \((\d+)\):', content)
    if not states_match:
        print("Warning: Could not find States section")
        return states
    
    expected_count = int(states_match.group(1))
    print(f"Expected states: {expected_count}")
    
    states_section = content[states_match.end():]
    
    # Pattern for state lines
    # Format: hash, ActivityName, DS, (JSON data): XML - screenshot.png
    state_pattern = re.compile(
        r'([a-f0-9]{64}),\s*'  # state_id
        r'([^,]+),\s*'  # activity name
        r'(\w+),\s*'  # data source
        r'\(([^)]*|\{[^}]*\}[^)]*)\):\s*'  # screen data (can be null or JSON)
        r'([^-]*)\s*-\s*'  # XML structure
        r'(\S+\.png|null)'  # screenshot
    )
    
    # Simpler pattern for basic parsing
    simple_state_pattern = re.compile(
        r'^([a-f0-9]{64}),\s*([^,]+),\s*(\w+),',
        re.MULTILINE
    )
    
    for match in simple_state_pattern.finditer(states_section):
        state_id = match.group(1)
        activity = match.group(2).strip()
        data_source = match.group(3)
        
        # Find the screenshot for this state
        line_start = match.start()
        line_end = states_section.find('\n', match.end())
        if line_end == -1:
            line_end = len(states_section)
        full_line = states_section[line_start:line_end]
        
        # Extract screenshot
        screenshot_match = re.search(r'-\s*(\S+\.png)', full_line)
        screenshot = screenshot_match.group(1) if screenshot_match else None
        
        state = {
            "id": state_id,
            "activity": activity,
            "data_source": data_source,
            "screenshot": screenshot
        }
        
        states.append(state)
    
    print(f"Parsed states: {len(states)}")
    return states


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "transitions.json"
    
    if not Path(input_file).exists():
        print(f"Error: Input file '{input_file}' not found")
        sys.exit(1)
    
    print(f"Parsing: {input_file}")
    print("-" * 50)
    
    # Parse transitions
    transitions = parse_transitions(input_file)
    
    # Parse states
    states = parse_states(input_file)
    
    # Create output structure
    output = {
        "metadata": {
            "source_file": input_file,
            "total_transitions": len(transitions),
            "total_states": len(states)
        },
        "transitions": transitions,
        "states": states
    }
    
    # Write JSON output
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)
    
    print("-" * 50)
    print(f"Output written to: {output_file}")
    
    # Print summary
    print("\n=== Summary ===")
    print(f"Transitions: {len(transitions)}")
    print(f"States: {len(states)}")
    
    # Action type breakdown
    action_counts = {}
    for t in transitions:
        action_name = t.get("action", {}).get("name", "unknown")
        action_counts[action_name] = action_counts.get(action_name, 0) + 1
    
    print("\nAction types:")
    for action, count in sorted(action_counts.items(), key=lambda x: -x[1]):
        print(f"  {action}: {count}")


if __name__ == "__main__":
    main()