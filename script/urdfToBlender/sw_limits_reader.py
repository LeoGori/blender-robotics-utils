import pandas as pd
import re
import xml.etree.ElementTree as ET
import os

# This file allows to read URDF limits from a .ini-like file and parse them into a pandas DataFrame.

def parse_ini(file_path):
    rows = []
    current_section = 'GLOBAL'

    with open(file_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1].strip()
                continue
            if " " in line:
                param, value = line.split(None, 1)
                rows.append({
                    "section": current_section,
                    "parameter": param,
                    "value": value.strip()
                })

    df = pd.DataFrame(rows)

    df['parsed_value'] = df['value'].apply(parse_values)

    return df

def parse_values(val):
    # Match only if it looks like a list of numbers (int or float) inside parentheses
    match = re.match(r"^\(\s*(-?\d+(?:\.\d+)?(?:\s+-?\d+(?:\.\d+)?)*?)\s*\)$", val)
    if match:
        try:
            return [float(x) for x in match.group(1).split()]
        except ValueError:
            return val  # fallback, just in case
        
    # Case 2: List of strings (literals)
    str_match = re.match(r"^\(\s*([a-zA-Z_][a-zA-Z0-9_]*\s*)+\)$", val)
    if str_match:
        return [x.strip() for x in val[1:-1].split()]  # Strip and split by whitespace

    # If neither, just return the original value
    return val  # return original string if not a numeric list nor string list


def extract_gazebo_plugins(urdf_string):
    # tree = ET.parse(urdf_path)
    # root = tree.getroot()
    root = ET.fromstring(urdf_string)
    gazebo_plugins = []
    for gazebo_tag in root.findall(".//gazebo"):
        plugin = gazebo_tag.find("plugin")
        if plugin is not None:
            name = plugin.attrib.get("name", "unknown")
            yarp_file = plugin.findtext("yarpConfigurationFile")
            gazebo_plugins.append((name, yarp_file))
    return gazebo_plugins

def extract_gazebo_plugins_from_urdf_path(urdf_path):
    tree = ET.parse(urdf_path)
    root = tree.getroot()
    gazebo_plugins = []
    for gazebo_tag in root.findall(".//gazebo"):
        plugin = gazebo_tag.find("plugin")
        if plugin is not None:
            name = plugin.attrib.get("name", "unknown")
            yarp_file = plugin.findtext("yarpConfigurationFile")
            gazebo_plugins.append((name, yarp_file))
    return gazebo_plugins

def get_body_parts_sw_pos_limits(urdf_string, body_parts):

    g_plugins = extract_gazebo_plugins(urdf_string)

    body_parts_ini = [v for k, v in g_plugins if any([bp in k for bp in body_parts])]

    bp_sw_limits = {}

    for bp_ini in body_parts_ini:
        
        bp_ini_path = os.path.join(bp_ini.split("://")[1])

        ini_df = parse_ini(bp_ini_path)

        joint_names = ini_df[ini_df["parameter"] == "jointNames"]["parsed_value"].iloc[0]
        print(joint_names)

        joint_pos_min = ini_df[ini_df["parameter"] == "jntPosMin"]["parsed_value"].iloc[0]
        print(joint_pos_min)

        joint_pos_max = ini_df[ini_df["parameter"] == "jntPosMax"]["parsed_value"].iloc[0]
        print(joint_pos_max)

        for joint_name, joint_min, joint_max in zip(joint_names, joint_pos_min, joint_pos_max):
            bp_sw_limits[joint_name] = (joint_min, joint_max)

    return bp_sw_limits

