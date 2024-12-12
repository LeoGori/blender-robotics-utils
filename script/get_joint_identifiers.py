import re
import argparse

def extract_joint_names(urdf_file, separate_with_comma, get_num):
    try:
        with open(urdf_file, 'r', encoding="ISO-8859-1") as file:
            urdf_content = file.read()
        
        # Regular expression to match joint names and types
        joint_name_pattern = r'joint name="([A-Za-z_]+)" type="([A-Za-z_]+)"'
        all_joints = re.findall(joint_name_pattern, urdf_content)
        
        # Filter out joints with type "fixed"
        # for name, joint_type in all_joints:
        #     print(name, joint_type)
        joint_names = [name for name, joint_type in all_joints if joint_type != "fixed"]
        
        joint_names = [n for n in joint_names if not any(x in n for x in ["wheel", "pinkie", "ring", "middle", "index", "thumb", "neck"])]

        # Output the extracted names
        if joint_names:
            if get_num:
                print(len(joint_names))
            else:
                separator = ', ' if separate_with_comma else ' '
                print(separator.join(joint_names))
        else:
            print("No joint names found matching the pattern.")

    except FileNotFoundError:
        print(f"Error: File '{urdf_file}' not found.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract joint names from a URDF file.")
    parser.add_argument("urdf_file", type=str, help="Path to the URDF file.")
    parser.add_argument("--separate_with_comma", action="store_true", 
                        help="Separate joint names with a comma instead of a space.")
    parser.add_argument("--get_num", action="store_true", 
                        help="get the number of joints instead of the names.")

    args = parser.parse_args()

    extract_joint_names(args.urdf_file, args.separate_with_comma, args.get_num)