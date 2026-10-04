#!/usr/bin/env python3
"""Serve/build the CT dashboard. Keep modality_dashboard.py and 1_update_data_ai.py alongside this file.
Run: python3 2_update_data_ct.py --port 8080
Build: add --offline --build rendered_ct.html
Data: add --data ct_data.json. See modalities_readme.md.
"""
from modality_dashboard import main

if __name__ == '__main__':
    main('ct')
