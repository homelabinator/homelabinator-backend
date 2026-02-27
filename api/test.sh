#!/usr/bin/env bash
curl -X POST -F "file=@text-snippet.txt" http://dell-poweredge:5000/generate-iso
