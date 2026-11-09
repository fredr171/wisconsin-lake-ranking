"""Run settings for lake_finder.py. Edit these, then run `python lake_finder.py`."""

# Only Wisconsin is supported: the lake data comes from the Wisconsin DNR.
STATE = "WI"

# Starting point for drive times. Placeholder: Minneapolis City Hall, a public
# landmark. Any address OpenStreetMap can geocode works. Changing it makes
# lake_finder.py recompute every drive time (a few minutes of routing calls).
START_ADDRESS = "350 S 5th St, Minneapolis, MN 55415"

# Keep only lakes within this many hours of real driving time (not straight-line distance).
MAX_DRIVE_HOURS = 3.5

# Ignore lakes smaller than this.
MIN_ACRES = 75
