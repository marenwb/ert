#!/usr/bin/env python3
import argparse
import json
import sys
import pathlib

def _build_arg_parser():
    arg_parser = argparse.ArgumentParser(
        description="Computes a polynomial as the sum of two second degree polynomials",
    )
    arg_parser.add_argument(
        "--input", type=pathlib.Path, nargs=2, required=True, help="Paths to the input files"
    )
    arg_parser.add_argument(
        "--output", type=pathlib.Path, required=True, help="Path to the output file"
    )
    return arg_parser

def _load_polynomials(input):
    with open(input[0], "r") as f1:
        poly1 = json.load(f1)
    with open(input[1], "r") as f2:
        poly2 = json.load(f2)
    return poly1, poly2        

def _sum_polynomials(poly1, poly2):
    return [i+j for i,j in zip(poly1,poly2)]

def _main():
    parser = _build_arg_parser()
    args = parser.parse_args()

    poly1, poly2 = _load_polynomials(args.input)
    result = _sum_polynomials(poly1, poly2)

    with open(args.output, "w") as f:
        json.dump(result, f)

if __name__ == "__main__":
    _main()
