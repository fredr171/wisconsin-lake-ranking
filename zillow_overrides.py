"""
Hand-picked Zillow search areas for lakes where the automatic box is a poor fit.

build_listing_report.py normally builds each lake's Zillow search box from its
center point, sized by sqrt(acres). For irregular lakes, or lakes with a
neighbor close by, that box can pull in homes on the wrong lake. The lakes
below use a hand-drawn box instead, found by adjusting the map on Zillow and
reading the bounds back from the URL.

Keyed by WBIC, not by name: a county can have several lakes with the same
name (Burnett County alone has two Sand Lakes), so name + county isn't unique.

WBIC: (west, east, south, north) in decimal degrees.
"""

MAP_BOUNDS = {
    1881100: (-91.94988, -91.89254, 45.56270, 45.60487),  # Silver Lake, Barron County
    1884100: (-91.61278, -91.49811, 45.79979, 45.88374),  # Stone Lake, Washburn County
    2495000: (-92.58909, -92.53176, 45.35166, 45.39399),  # Sand Lake, Polk County
    2497100: (-91.70336, -91.64602, 46.24315, 46.28481),  # Simms Lake, Douglas County
    2079000: (-92.14788, -92.09055, 45.32192, 45.36427),  # Big Moon Lake, Barron County
    1670030: (-90.75165, -90.69432, 44.26851, 44.31164),  # Wazee Lake, Jackson County
    2107500: (-91.76619, -91.70886, 45.70861, 45.75066),  # Big Devil Lake, Washburn County
    2467900: (-91.33663, -91.27929, 46.23824, 46.27990),  # Hammil Lake, Bayfield County
    2106800: (-91.79842, -91.56908, 45.63983, 45.80808),  # Long Lake (3,478 acres), Washburn County
    2899200: (-91.26561, -91.23694, 46.35442, 46.37521),  # Cisco Lake, Bayfield County
    2109300: (-91.58749, -91.53015, 45.77672, 45.81873),  # Slim Lake, Washburn County
    2503500: (-91.83584, -91.77850, 46.19442, 46.23611),  # Two Mile Lake, Douglas County
    2460700: (-92.20498, -92.14765, 46.02195, 46.06377),  # Deer Lake, Burnett County
    2897100: (-91.17398, -91.11664, 46.24183, 46.28349),  # Diamond Lake, Bayfield County
    2709800: (-91.96581, -91.90847, 45.91643, 45.95834),  # Dunn Lake, Washburn County
    2275100: (-90.79359, -90.67892, 45.70984, 45.79393),  # Connors Lake, Sawyer County
    2474800: (-91.76284, -91.70551, 45.75256, 45.79458),  # Leesome Lake, Washburn County
    2897300: (-91.17403, -91.11669, 46.22558, 46.26725),  # Crystal Lake (117 acres), Bayfield County
    2393500: (-91.54685, -91.48952, 45.74058, 45.78261),  # Sissabagama Lake, Sawyer County
    2621100: (-92.47786, -92.36319, 45.45236, 45.53683),  # Half Moon Lake (550 acres), Polk County
    2865000: (-91.75863, -91.64396, 46.46104, 46.54399),  # Lake Nebagamon, Douglas County
    2899400: (-91.28981, -91.23247, 46.32313, 46.36472),  # Drummond Lake, Bayfield County
    2461100: (-92.39510, -92.28043, 45.86734, 45.95119),  # Devils Lake, Burnett County
    2734500: (-91.12324, -91.06590, 46.24166, 46.28331),  # Trapper Lake, Bayfield County
    1841300: (-91.27823, -91.24956, 46.01175, 46.03267),  # Clear Lake (77 acres), Sawyer County
    1833300: (-91.67637, -91.61904, 45.68602, 45.72810),  # Bass Lake (101 acres), Washburn County
    2092500: (-91.49617, -91.46750, 45.26829, 45.28949),  # Axhandle Lake, Chippewa County
    2489400: (-91.37767, -91.32034, 46.32148, 46.36308),  # Pigeon Lake, Bayfield County
    2393200: (-91.55299, -91.43832, 45.81024, 45.89417),  # Sand Lake, Sawyer County
    2616100: (-92.57021, -92.51287, 45.25549, 45.29789),  # Church Pine Lake, Polk County
    2395600: (-91.37561, -91.25956, 45.97271, 46.05604),  # Round Lake, Sawyer County
    2694000: (-91.93021, -91.81417, 46.17237, 46.25540),  # Whitefish Lake, Douglas County
    2392000: (-91.50331, -91.38726, 45.82108, 45.90464),  # Whitefish Lake, Sawyer County
    2495100: (-92.23129, -92.11525, 45.87643, 45.95991),  # Sand Lake, Burnett County (900 acres)
    1835700: (-91.28016, -91.22214, 45.86038, 45.90215),  # Blueberry Lake, Sawyer County
    2691900: (-91.96552, -91.93651, 46.11816, 46.13895),  # Middle Kimball Lake, Washburn County
    2693800: (-91.87784, -91.84883, 46.18303, 46.20380),  # Leader Lake, Douglas County
    2390800: (-91.56194, -91.32985, 45.79251, 45.95959),  # Lac Courte Oreilles, Sawyer County
    2903200: (-91.39090, -91.33288, 46.49789, 46.53917),  # Hart Lake, Bayfield County
    2479900: (-92.57915, -92.55014, 45.23345, 45.25457),  # Lower Pine Lake, Polk County
    2674100: (-92.15929, -92.10127, 45.96989, 46.01157),  # Long Lake, Burnett County (222 acres)
    2900200: (-91.36687, -91.13478, 46.19679, 46.36265),  # Lake Owen, Bayfield County
    2391200: (-91.47337, -91.35733, 45.89517, 45.97862),  # Grindstone Lake, Sawyer County
    2674200: (-92.16402, -92.10599, 45.97576, 46.01744),  # Des Moines Lake, Burnett County
    2693700: (-91.90353, -91.84551, 46.16264, 46.20418),  # Bond Lake, Douglas County
    2496300: (-91.95762, -91.84157, 45.69209, 45.77584),  # Shell Lake, Washburn County
    2476000: (-92.17633, -92.14732, 45.97889, 45.99973),  # Little Bear Lake, Burnett County
    2494900: (-91.54171, -91.51270, 46.35902, 46.37972),  # Sand Bar Lake, Bayfield County
    2903100: (-91.40059, -91.34257, 46.48740, 46.52869),  # Twin Bear Lake, Bayfield County
    2457600: (-92.41360, -92.35558, 45.74596, 45.78781),  # Clear Lake, Burnett County
    2742700: (-91.53696, -91.42092, 46.26809, 46.35098),  # Upper Eau Claire Lake, Bayfield County
    2451900: (-91.65343, -91.59541, 45.92155, 45.96327),  # Bass Lake, Washburn County (187 acres, rank #123)
    2451300: (-92.02419, -91.96617, 45.89221, 45.93395),  # Bass Lake, Washburn County (132 acres, rank #31)
    2229200: (-91.06413, -90.94809, 45.48142, 45.56548),  # Dairyland Reservoir (Flambeau), Rusk County
    2630200: (-92.16320, -92.10517, 45.42536, 45.46745),  # Echo Lake, Barron County
    2494500: (-91.98693, -91.92891, 46.04339, 46.08502),  # South Twin Lake, Washburn County
    2490500: (-92.24245, -92.18443, 45.49699, 45.53903),  # Pipe Lake, Polk County
    2742500: (-91.53620, -91.47818, 46.29687, 46.33831),  # Bony Lake, Bayfield County
    2661100: (-92.13706, -92.07903, 45.56944, 45.61142),  # Sand Lake, Barron County (318 acres)
    2619400: (-92.58077, -92.46473, 45.36052, 45.44477),  # Deer Lake, Polk County
    1346900: (-90.22941, -90.11337, 44.03056, 44.11677),  # Number Two Pool, Juneau County
    2651800: (-92.50092, -92.44290, 45.73548, 45.77734),  # Dunham Lake, Burnett County
    2672500: (-92.24720, -92.18918, 45.98607, 46.02774),  # Twentysix Lake, Burnett County
    2760100: (-91.48882, -91.43079, 46.53469, 46.57595),  # Deep Lake, Bayfield County
    2903700: (-91.39608, -91.33805, 46.50908, 46.55036),  # Lake Millicent, Bayfield County
    2678300: (-92.11983, -92.06181, 45.86602, 45.90779),  # Benoit Lake, Burnett County
    1875900: (-91.30946, -91.25144, 45.31563, 45.35780),  # Pulaski Lake, Rusk County
    2171000: (-91.36696, -91.30894, 45.09649, 45.13883),  # Cornell Lake, Chippewa County
    2453300: (-91.93383, -91.87650, 46.05274, 46.09454),  # Big Bass Lake, Washburn County
    2903800: (-91.40395, -91.34593, 46.50722, 46.54849),  # Buskey Bay, Bayfield County
    1849100: (-91.52982, -91.47180, 45.28473, 45.32692),  # Fish Lake, Rusk County
    2677200: (-92.25068, -92.19335, 45.77742, 45.81943),  # Warner Lake, Burnett County
    2480800: (-92.20640, -92.14907, 45.87857, 45.92050),  # Mallard Lake, Burnett County
    2866200: (-91.80358, -91.68891, 46.42631, 46.50931),  # Lake Minnesuing, Douglas County
    2432000: (-91.23736, -91.18002, 45.87861, 45.92054),  # Two Boys Lake, Sawyer County
    2501700: (-91.55179, -91.49445, 46.34110, 46.38268),  # Tomahawk Lake, Bayfield County
    2742100: (-91.57874, -91.46407, 46.25389, 46.33715),  # Middle Eau Claire Lake, Bayfield County
    2473500: (-91.25188, -91.19455, 46.22297, 46.26464),  # Lake Tahkodah, Bayfield County
    2275300: (-90.74408, -90.68675, 45.75036, 45.79239),  # Lake of the Pines, Sawyer County
    2628100: (-92.44652, -92.33185, 45.49269, 45.57710),  # Bone Lake, Polk County
    2598600: (-92.28000, -92.22267, 45.79681, 45.83880),  # Viola Lake, Burnett County
    2671000: (-92.36173, -92.30439, 45.95345, 45.99532),  # Love Lake, Burnett County
    2902900: (-91.38407, -91.32673, 46.47514, 46.51662),  # Eagle Lake, Bayfield County
    2046500: (-91.23965, -91.18231, 45.64307, 45.68518),  # Windfall Lake, Sawyer County
    2712000: (-91.91810, -91.80343, 45.88302, 45.96685),  # Trego Lake, Washburn County
    2499000: (-92.64409, -92.58675, 45.15959, 45.20206),  # Apple Lake, St. Croix County
    2350200: (-91.44236, -91.32769, 45.28137, 45.36610),  # Island Lake, Rusk County
    2624000: (-92.39931, -92.34198, 45.30080, 45.34316),  # Pike Lake, Polk County
    2649800: (-92.60825, -92.55092, 45.72079, 45.76284),  # Wood Lake, Burnett County
    2670600: (-92.35691, -92.29957, 45.96629, 46.00815),  # Minerva Lake, Burnett County
    2489200: (-91.54286, -91.48552, 46.30658, 46.34818),  # Pickerel Lake, Bayfield County
    2499200: (-92.28911, -92.26044, 46.03595, 46.05686),  # Staples Lake, Burnett County
    2112800: (-91.60657, -91.54855, 45.62964, 45.67158),  # Balsam Lake, Washburn County
}
