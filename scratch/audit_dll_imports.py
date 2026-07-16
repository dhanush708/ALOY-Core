import os
import sys
import pefile
from pathlib import Path

def get_imports(pe_path):
    try:
        pe = pefile.PE(pe_path)
        imports = []
        if not hasattr(pe, 'DIRECTORY_ENTRY_IMPORT'):
            return []
        for entry in pe.DIRECTORY_ENTRY_IMPORT:
            dll_name = entry.dll.decode('utf-8')
            imports.append(dll_name)
        return imports
    except Exception as e:
        print(f"Error reading {pe_path}: {e}")
        return []

def audit_file(pe_path, bundle_internal_dir):
    print(f"\nAuditing PE: {pe_path}")
    imports = get_imports(pe_path)
    print(f"Imports ({len(imports)}):")
    
    missing_in_bundle = []
    found_system = []
    
    system_32 = Path("C:/Windows/System32")
    
    for dll in imports:
        dll_lower = dll.lower()
        # Check if present in internal bundle
        in_bundle = (bundle_internal_dir / dll_lower).exists() or (bundle_internal_dir / dll).exists()
        # Check if present in System32
        in_sys32 = (system_32 / dll_lower).exists() or (system_32 / dll).exists() or dll_lower.startswith("api-ms-win")
        
        status = "OK (Bundle)" if in_bundle else ("OK (System32)" if in_sys32 else "MISSING")
        print(f"  - {dll:<35}: {status}")
        
        if not in_bundle and not in_sys32:
            missing_in_bundle.append(dll)
            
    return missing_in_bundle

def main():
    bundle_internal = Path("dist/ALOY/_internal")
    aloy_exe = Path("dist/ALOY/ALOY.exe")
    python_dll = bundle_internal / "python311.dll"
    sqlite_vec_dll = bundle_internal / "sqlite_vec" / "vec0.dll"
    
    if not aloy_exe.exists():
        print(f"Error: {aloy_exe} does not exist. Run PyInstaller build first.")
        return
        
    missing_aloy = audit_file(aloy_exe, bundle_internal)
    missing_py = audit_file(python_dll, bundle_internal)
    
    if sqlite_vec_dll.exists():
        missing_vec = audit_file(sqlite_vec_dll, bundle_internal)
    else:
        print(f"\nvec0.dll not found at {sqlite_vec_dll}")
        missing_vec = []
        
    print("\n================ SUMMARY ================")
    print(f"Missing for ALOY.exe: {missing_aloy}")
    print(f"Missing for python311.dll: {missing_py}")
    if sqlite_vec_dll.exists():
        print(f"Missing for vec0.dll: {missing_vec}")

if __name__ == "__main__":
    main()
