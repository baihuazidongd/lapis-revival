#!/usr/bin/env python
"""boot_state.py FRAME.png [--home REF.png] [--values] -- name the boot-chain state, or "unknown".

plate_diff alone cannot drive a cold start: it reads only the top-left title plate, which separates
home from every sub-page but reports a near-identical number for the title screen, the ご注意 legal
page, the OP movie and a campaign banner over home. A driver that treats those as one state taps
title-screen coordinates at a dialog and then reports pages it never navigated to.

Every crop is a fixed box in 1280x720 space and every cut below is measured against a home reference
captured on the SAME device at the SAME logical size (see --home). Two frames of this tablet's home
six seconds apart differ by 1.47 and 1.72 there; the nearest non-home frame in the set is 51.59. The
home cut therefore sits at 25 - fourteen times the noise floor and half the distance to the closest
thing it must reject. The old 8.0 cut was measured against a stale save's header and read 7.91 for a
genuine home frame, which is how a sweep aborts on "unknown" while looking straight at the town.

This names the BOOT CHAIN only, and that limit is load-bearing. Every sub-page was scored against the
same five features and they collide with any state name you pick: the 報酬 page's pink button reads
pink 69.0, the 課題 and 设置 pages read centre-white 61.2 / 60.5, and eleven of the twelve pages read a
left rail above 120 so they all look like the title screen. There is no pixel statistic that separates
"an anime frame with no UI" from "a page", so no "movie" state is defined - an OP frame lands on
title / campaign / unknown and cold() treats unknown as "wait, this is a video", which is both honest
and what actually happens. to_home() must therefore only ever act on the four modal states below and
leave everything else to the page's own back chevron.

Two further features were measured on 2026-10-02 and are recorded here so nobody spends a cycle on
them again. The left-edge skip tab on the OP movie (white pixels in x0-16, y228-342) reads 1082-1172
on movie frames but 1162 on the 課題 page, 1440 on 通信 and 1824 on 報酬 - it counts white artwork at
the screen edge, not a control. The bottom nav row as a "is home underneath?" test fails both ways:
raw mean-abs against a home reference gives 85.5 / 88.5 for the campaign banner against 53.8-92.3 for
real sub-pages, and brightness-normalised gives 0.441 / 0.465 against 0.291-0.547, because the modal
scrim is not a pure scalar multiply and the panel covers part of the row anyway.

  frame            plate  bright    pink    rail  ctrWhite   state
  home (x4)        0-1.7   140-143 -16..-20  97-155   1.6-2.2%  home
  legal notice pg  124.4   247.2     0.0   255.0    88.96%      legal
  terms agree dlg   74.5   195.1   110.6   221.7    84.85%      terms
  campaign banner   75.2   143.8    -0.2    60.7    20.30%      campaign
  notice dialog     68.1   185.0     0.0    76.2    98.19%      notice
  OP movie frames   51-131   61-145  -1..33    0-166    1-12%    title / campaign / unknown
  --- swept sub-pages: every one of these must fall through to the page back tap ---
  reward houhou     113.7   196.3    69.0   243.4    42.40%      title
  missions kadai    113.7   191.7    -7.6   152.4    61.20%      title
  settings settei   115.6   207.9   -21.5   172.9    60.50%      title
  comms tsuushin    115.5   186.0   -23.8   105.2    57.60%      unknown
  witch majo        115.7   157.1    -8.3   102.3    26.70%      unknown
  stages quest      112.2   147.9   -40.5   141.7    10.20%      title
  shop              112.3   167.6   -22.8   155.7    17.50%      title

"unknown" is deliberate: an unclassified frame gets no tap. Guessing a coordinate is how a previous
pass destroyed its own results.
"""
import sys
import numpy as np
from PIL import Image

def load(p):
    return np.array(Image.open(p).convert('RGB')).astype(np.int16)

frame = load(sys.argv[1])
H, W = frame.shape[:2]
ref_path = 'C:/lapisbuild/delivery/x_state_tablet.png'
if '--home' in sys.argv:
    ref_path = sys.argv[sys.argv.index('--home') + 1]
# The home cut is a property of the REFERENCE, not of the game. Measured 2026-10-03: against the
# tablet's 3D-home reference, genuine home frames read 1.47 / 1.72 and the 2D home reads 15.13, while
# the nearest non-home frame in the whole boot set is 51.59 - so 25 is right there. Against the AVD's
# own 3D-home reference the same box is low-contrast (mean 55.7): home reads 3.73 but a BATTLE frame
# reads 20.99 / 21.40, so 25 lets a battle through as "home" and the driver then taps the nav plates
# into the combat HUD. The AVD passes --cut 12, which is between its own 3.73 and its own 20.99.
cut = 25.0
if '--cut' in sys.argv:
    cut = float(sys.argv[sys.argv.index('--cut') + 1])
home_img = Image.open(ref_path).convert('RGB')
# The boxes below are absolute pixels, so a reference from another geometry is not a reference. The
# one legitimate mismatch is a capture that came back portrait: rotate it instead of failing, and
# refuse anything else rather than silently scoring blank UI (which is what produced "pink=0.0 while
# a big pink 同意 button is on screen").
if home_img.size != (W, H):
    if home_img.size == (H, W):
        home_img = home_img.rotate(90, expand=True)
    else:
        sys.stderr.write('reference %s is %s, frame is %dx%d - capture a home reference on this device\n'
                         % (ref_path, home_img.size, W, H))
        sys.exit(3)
home = np.array(home_img).astype(np.int16)

plate = float(np.abs(frame[14:62, 55:340] - home[14:62, 55:340]).mean())
bright = float(frame.mean())
pink = float(frame[612:656, 895:1035, 0].mean() - frame[612:656, 895:1035, 1].mean())
rail = float(frame[250:300, 40:150].mean())
box = frame[int(.25 * H):int(.75 * H), int(.25 * W):int(.75 * W)]
ctr = float((box.min(axis=2) > 225).mean()) * 100.0

if plate <= cut:
    state = 'home'
elif pink > 90.0:
    # 110.6 on the real 同意 dialog; the 報酬 page's pink claim button is the nearest thing else in
    # the whole set at 69.0, so the old cut of 50 called that page "terms".
    state = 'terms'
elif ctr > 90.0 and rail < 200.0:
    # The notice dialog is a nearly pure white panel over the town: 98.2 / 98.24 measured, and the
    # whitest sub-page (the 課題 list) only reaches 61.2. The old cut of 60 called 課題 and 设置 "notice".
    state = 'notice'
elif ctr > 80.0 and rail > 200.0:
    # The ご注意 legal page is also near-white (89.0) but it fills the left rail with paper (255.0),
    # while every dialog over home shows the dimmed town there (76-95).
    state = 'legal'
elif bright < 60.0:
    state = 'play'
elif rail > 120.0:
    state = 'title'
elif rail < 90.0:
    state = 'campaign'
else:
    state = 'unknown'

if '--values' in sys.argv:
    sys.stdout.write('%s plate=%.2f bright=%.1f pink=%.1f rail=%.1f ctr=%.1f\n'
                     % (state, plate, bright, pink, rail, ctr))
else:
    sys.stdout.write(state + '\n')
