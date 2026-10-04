#!/usr/bin/env python3
"""Serve/build the PET dashboard. Keep modality_dashboard.py and 1_update_data_ai.py alongside this file.
Run: python3 4_update_data_pet.py --port 8080
Build: add --build rendered_pet.html
Offline design/data checks: add --offline.
Data: add --data pet_data.json. See modalities_readme.md.
"""
from modality_dashboard import main

if __name__ == '__main__':
    main('pet')
