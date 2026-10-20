#!/usr/bin/env python
"""plate_diff.py A.png B.png — mean abs pixel difference over the page-title plate.

Home is a live 3D scene: two home frames differ by 15.8/255 over the whole frame, and PNG
byte size is worse than useless (1345575 / 1346706 / 1347406 all "look like" home's
1348889). The title plate at the top-left is the one static UI region: two home frames
differ by 0.32 there, home vs any sub-page by 108-115. Threshold 3.0.
"""
import sys
import numpy as np
from PIL import Image

a = np.array(Image.open(sys.argv[1]).convert('RGB')).astype(np.int16)
b = np.array(Image.open(sys.argv[2]).convert('RGB')).astype(np.int16)
print('%.3f' % float(np.abs(a[14:62, 55:340] - b[14:62, 55:340]).mean()))
