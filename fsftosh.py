#!/usr/bin/env python3
"""
This script converts an FSF file (as generated by the TCL possum:write procedure)
into a shell script that runs the various FSL/POSSUM commands. It:
 
  • Parses the FSF file (which contains lines like:
        set entries($w,KEY) "value"
    )
  • Computes derived values (for example new dimensions for fslcreatehd)
  • Builds a shell script that:
      - Creates the output directory.
      - Processes the input object (brain.nii.gz) to obtain its dimensions,
        and creates a brain reference image.
      - Registers the input object.
      - Copies input files:
            • MRpar (MR parameters)
            • Slice profile (slcprof)
            • Motion file (motion)
            • Activation image (T2.nii.gz) and its timecourse (T2timecourse)
            • B0 inhomogeneity file (b0A_dA.nii.gz) is processed
      - For the pulse sequence:
            • For standard “epi” or “ge” sequences, a pulse command is generated.
            • For a custom pulse sequence, the script copies all pulse files:
              pulse, pulse.info, pulse.readme, pulse.posx, pulse.posy, and pulse.posz.
      - Processes the noise file by writing out a file (named “noise”) that
        contains either an SNR or sigma line.
      - Finally, the possumX command is appended.
      
The POSSUM setup file (possum.fsf) is written as well so that it can be reloaded
by the GUI.
"""

import argparse
import re
import math

def parse_fsf(fsf_filename):
    """
    Parse the FSF file to extract key–value pairs.
    Expected lines look like: 
        set entries($w,KEY) "value"
    Returns a dictionary mapping KEY -> value.
    """
    params = {}
    pattern = re.compile(r'set entries\(\$w,([^)]*)\)\s+"([^"]*)"')
    with open(fsf_filename, 'r') as f:
        for line in f:
            m = pattern.search(line)
            if m:
                key = m.group(1).strip()
                value = m.group(2).strip()
                params[key] = value
    return params

def compute_brain_ref(params):
    """
    Compute parameters for creating the brain reference image.
    Assumes the FSF file contains input dimensions (inNx, inNy, inNz, inNt),
    voxel sizes (vcX, vcY, vcZ), desired output dimensions (outsize_nx, outsize_ny, outsize_nz)
    and output voxel sizes (outsize_dx, outsize_dy, outsize_dz), plus a slice-sampling factor
    and a slice-selection direction (slcselect).
    Returns a tuple:
      (newdim1, newdim2, newdim3, inNt, newpixdim1, newpixdim2, newpixdim3, pixdim4)
    """
    inNx = float(params.get("inNx", "0"))
    inNy = float(params.get("inNy", "0"))
    inNz = float(params.get("inNz", "0"))
    inNt = params.get("inNt", "1")
    vcX = float(params.get("vcX", "1"))
    vcY = float(params.get("vcY", "1"))
    vcZ = float(params.get("vcZ", "1"))

    outsize_nx = int(params.get("outsize_nx", str(int(inNx))))
    outsize_ny = int(params.get("outsize_ny", str(int(inNy))))
    outsize_nz = int(params.get("outsize_nz", str(int(inNz))))
    outsize_dx = float(params.get("outsize_dx", "1"))
    outsize_dy = float(params.get("outsize_dy", "1"))
    outsize_dz = float(params.get("outsize_dz", "1"))
    slcsampfactor = float(params.get("slcsampfactor", "1"))
    slcselect = params.get("slcselect", "z")

    newdim1, newdim2, newdim3 = inNx, inNy, inNz
    newpixdim1, newpixdim2, newpixdim3 = vcX, vcY, vcZ

    if slcselect.lower() == "x":
        newpixdim1 = outsize_dx / slcsampfactor
        newdim1 = round(inNx * vcX / newpixdim1)
    elif slcselect.lower() == "y":
        newpixdim2 = outsize_dy / slcsampfactor
        newdim2 = round(inNy * vcY / newpixdim2)
    else:  # default is z
        newpixdim3 = outsize_dz / slcsampfactor
        newdim3 = round(inNz * vcZ / newpixdim3)

    pixdim4 = params.get("inNt", "1")
    return newdim1, newdim2, newdim3, inNt, newpixdim1, newpixdim2, newpixdim3, pixdim4

def generate_shell_commands(params):
    """
    Generate a list of shell command strings.
    In addition to processing the brain image (obvol), MR parameters, slice profile,
    motion file, activation files, and B0 inhomogeneity file, this function also:
      - Builds a pulse sequence command for epi/ge sequences (or copies custom pulse files)
      - Processes the noise file
      - Finally appends the possumX execution command.
    """
    # Directories
    FSLDIR = params.get("FSLDIR", "/usr/local/fsl")
    POSSUMDIR = params.get("POSSUMDIR", FSLDIR)
    out = params.get("out", "./simdir")
    
    # Files
    obvol = params.get("obvol", "")         # brain.nii.gz (input object)
    mrpar = params.get("mrpar", "")         # MRpar file
    slcprof = params.get("slcprof", "")     # slice profile
    mot = params.get("mot", "")             # motion file
    act1 = params.get("act1", "")           # activation image (T2.nii.gz)
    act2 = params.get("act2", "")           # activation timecourse (T2timecourse)
    b0f = params.get("b0f", "")             # B0 inhomogeneity file (e.g. b0A_dA.nii.gz)

    # Pulse parameters
    seqtype = params.get("seqtype", "epi")
    te = params.get("te", "0.03")
    tr = params.get("tr", "3")
    trslc = params.get("trslc", "0.12")
    numvol = params.get("numvol", "1")
    bw = params.get("bw", "100000")
    readgrad = params.get("readgrad", "x")
    phencode = params.get("phencode", "y")
    slcselect = params.get("slcselect", "z")
    plus = params.get("plus", "+")
    maxG = params.get("maxG", "0.055")
    riseT = params.get("riseT", "0.00022")
    # For custom pulse sequence, the GUI sets "cuspulse"
    cuspulse = params.get("cuspulse", "")

    # Noise parameters
    noise_yn = params.get("noise_yn", "0")
    noiseunits = params.get("noiseunits", "sigma")
    noisesnr = params.get("noisesnr", "10")
    noisesigma = params.get("noisesigma", "0")

    # Other processing parameters
    numproc = params.get("numproc", "1")
    segs = params.get("segs", "10000")

    # Compute new brain reference dimensions
    newdim1, newdim2, newdim3, inNt, newpixdim1, newpixdim2, newpixdim3, pixdim4 = compute_brain_ref(params)

    cmds = []
    # Create output directory
    cmds.append(f"mkdir -p {out}")

    # Process input object: create brain reference and register input
    cmds.append(f"{FSLDIR}/bin/fslcreatehd {newdim1} {newdim2} {newdim3} {inNt} {newpixdim1} {newpixdim2} {newpixdim3} {pixdim4} 0 0 0 16 {out}/brainref")
    cmds.append(f"{FSLDIR}/bin/flirt -in {obvol} -ref {out}/brainref -applyxfm -out {out}/brain")

    # Copy MRpar, slice profile and motion file
    if mrpar:
        cmds.append(f"cp {mrpar} {out}/MRpar")
    if slcprof:
        cmds.append(f"cp {slcprof} {out}/slcprof")
    if mot:
        cmds.append(f"cp {mot} {out}/motion")

    # Process Activation:
    # Register the 3D activation image (T2.nii.gz) to the brain reference
    if act1:
        cmds.append(f"{FSLDIR}/bin/flirt -in {act1} -ref {out}/brainref -applyxfm -out {out}/T2")
    # Copy the activation timecourse (T2timecourse)
    if act2:
        cmds.append(f"cp {act2} {out}/T2timecourse")

    # Process B0 inhomogeneity file (if provided) – b0f here is like the b0A_dA.nii.gz input.
    if b0f:
        # For example, register and extract the relevant slice (here we extract a single slice using fslroi)
        cmds.append(f"{FSLDIR}/bin/flirt -in {b0f} -ref {out}/brainref -applyxfm -out {out}/b0newref")
        cmds.append(f"{FSLDIR}/bin/fslroi {out}/b0newref {out}/b0z_dz.nii.gz 0 1")
        if params.get("b0units", "ppm").lower() == "ppm":
            cmds.append(f"{FSLDIR}/bin/fslmaths {out}/b0z_dz.nii.gz -mul {params.get('b0fieldstrength', '1.5')} -div 1000000 {out}/b0z_dz.nii.gz")

    # Pulse sequence processing:
    if seqtype.lower() in ["epi", "ge"]:
        pulse_cmd = (f"{POSSUMDIR}/bin/pulse -i {out}/brain -o {out}/pulse "
                     f"--seq={seqtype} --te={te} --tr={tr} ")
        if seqtype.lower() == "epi":
            pulse_cmd += f"--trslc={trslc} "
        pulse_cmd += (f"--nx={params.get('outsize_nx', '64')} --ny={params.get('outsize_ny', '64')} "
                      f"--numslc={params.get('outsize_nz', '1')} --dx={params.get('outsize_dx', '4.0')} "
                      f"--dy={params.get('outsize_dy', '4.0')} --slcthk={newpixdim3} "
                      f"--numvol={numvol} --zstart=0 --bw={bw} "
                      f"--readdir={readgrad}{plus} --phasedir={phencode}{plus} --slcdir={slcselect}{plus} "
                      f"--maxG={maxG} --riset={riseT} -v")
        cmds.append(pulse_cmd + f" >> {out}/possum.log 2>&1")
    else:
        # Custom pulse sequence: copy pulse and all its companion files
        if cuspulse:
            for ext in ["", ".info", ".readme", ".posx", ".posy", ".posz", ".com"]:
                cmds.append(f"cp {cuspulse}{ext} {out}/pulse{ext}")

    # Process the noise file – mimic the TCL behavior:
    if noise_yn == "1":
        if noiseunits.lower() == "snr":
            noise_line = f"snr {noisesnr}"
        else:
            noise_line = f"sigma {noisesigma}"
        cmds.append(f'echo "{noise_line}" > {out}/noise')

    # Finally, add the possumX simulation command.
    possumX_cmd = f"{POSSUMDIR}/bin/possumX {out} -n {numproc} -t {params.get('proctime', '0')} -s {segs} >> {out}/possum.log 2>&1"
    cmds.append(possumX_cmd)

    # (Optionally, one could also generate the possum setup file (possum.fsf) by
    # writing out the current parameter set.)
    cmds.append(f"echo 'POSSUM setup file generated.' > {out}/possum.fsf")

    return cmds

def main():
    parser = argparse.ArgumentParser(description="Convert FSF file to a shell script that runs FSL/POSSUM commands.")
    parser.add_argument("fsf_file", help="Input FSF file (as generated by POSSUM:write)")
    parser.add_argument("output_shell", help="Output shell script file")
    args = parser.parse_args()

    # Parse FSF file to get all parameters
    params = parse_fsf(args.fsf_file)
    
    # Generate shell commands that process every input file accordingly
    cmds = generate_shell_commands(params)
    
    # Write the commands to the output shell script
    with open(args.output_shell, 'w') as outf:
        outf.write("#!/bin/sh\n\n")
        for cmd in cmds:
            outf.write(cmd + "\n")
    print(f"Shell script written to {args.output_shell}")

if __name__ == "__main__":
    main()