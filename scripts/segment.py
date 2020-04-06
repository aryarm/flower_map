#!/usr/bin/env python3
import argparse

parser = argparse.ArgumentParser(description='Segment the image into objects.')
parser.add_argument(
    "image",
    help="a path to the image to segment"
)
parser.add_argument(
    "out", type=argparse.FileType('w', encoding='UTF-8'),
    help="the path to a file in which to store the coordinates of each extracted object"
)
args = parser.parse_args()

import features
import cv2 as cv
import numpy as np
from test_util import *


def sliding_window(img, size, fnctn, num_features=1, skip=0):
    """
        run fnctn over each sliding, square window of len/width 2*size+1, skipping every skip pixel
    """
    # make a shape x 6 array, since there are 6 texture features
    new = np.empty(img.shape+(num_features,))
    # run a sliding window over the i and j indices
    for i in range(0, img.shape[0], skip):
        # we adjust for windows that would otherwise go over the edge of the frame
        i1 = max(0, i-size)
        i2 = min(i+size+1, img.shape[0])
        next_i = min(i+skip, img.shape[0])
        for j in range(0, img.shape[1], skip):
            j1 = max(0, j-size)
            j2 = min(j+size+1, img.shape[1])
            next_j = min(j+skip, img.shape[1])
            # call the function
            new[i:next_i,j:next_j,:] = fnctn(img[i1:i2,j1:j2])
    return new

print('loading image')
img = cv.imread(args.image)

print('calculating textures (this may take a while)')
gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
if True:
    texture = sliding_window(gray, 2, features.glcm, 6, 30)
else:
    texture = np.load("temp/texture.npy")
thresh_contrast = cv.threshold(texture[:,:,0], 1300, 255, cv.THRESH_BINARY)[1]

print('performing morphological operations to remove noise from texture')
thresh_contrast_closing = cv.morphologyEx(thresh_contrast, cv.MORPH_CLOSE, np.ones((16,16), np.uint8), iterations = 4)
thresh_contrast_opening = cv.morphologyEx(thresh_contrast_closing, cv.MORPH_OPEN, np.ones((31,31), np.uint8), iterations = 2)

# plot_img(create_arr([img, thresh_contrast, thresh_contrast_closing, thresh_contrast_opening], 2,2))

# blur image to remove noise from flowers
print('blurring image to remove noise')
blur = cv.GaussianBlur(img,(5,5),60)

print('creating thresholded matrix')
# hsv = cv.cvtColor(img,cv.COLOR_BGR2HSV)
# order of colors is blue, green, red
thresh_green_orig = cv.bitwise_not(cv.inRange(blur, (0, 92, 0), (255, 255, 255)))
thresh_green2_orig = cv.bitwise_not(cv.inRange(img, (0, 85, 0), (255, 255, 255)))

thresh_green = np.logical_or(thresh_contrast_opening, thresh_green_orig).astype(np.float)*255
thresh_green2 = np.logical_or(thresh_contrast_opening, thresh_green2_orig).astype(np.float)*255

# plot_img(create_arr([img, thresh_green2_orig, thresh_green2, blur, thresh_green_orig, thresh_green], 2, 3), create_arr(['original', 'green', 'green + contrast', 'blur', 'blurred green', 'blurred green + contrast'], 2, 3))

# noise removal
print('performing morphological operations to remove noise from green')
opening1 = cv.morphologyEx(thresh_green,cv.MORPH_OPEN, np.ones((5,5),np.uint8), iterations = 1)
closing1 = cv.morphologyEx(opening1, cv.MORPH_CLOSE, np.ones((5,5),np.uint8), iterations = 5)
confident= cv.morphologyEx(closing1,cv.MORPH_OPEN, np.ones((6,6),np.uint8), iterations = 23)
opening = cv.morphologyEx(closing1, cv.MORPH_OPEN, np.ones((3,3),np.uint8), iterations = 5)
closing = cv.morphologyEx(opening, cv.MORPH_CLOSE, np.ones((5,5),np.uint8), iterations = 15)

topening1 = cv.morphologyEx(thresh_green2,cv.MORPH_OPEN, np.ones((5,5),np.uint8), iterations = 1)
tclosing1 = cv.morphologyEx(topening1, cv.MORPH_CLOSE, np.ones((5,5),np.uint8), iterations = 7)
tconfident = cv.morphologyEx(tclosing1,cv.MORPH_OPEN, np.ones((5,5),np.uint8), iterations = 23)
topening = cv.morphologyEx(tclosing1, cv.MORPH_OPEN, np.ones((5,5),np.uint8), iterations = 5)
tclosing = cv.morphologyEx(topening, cv.MORPH_CLOSE, np.ones((5,5),np.uint8), iterations = 15)

# plot_img(create_arr([img, topening1, tclosing1, topening, tclosing, blur, opening1, closing1, opening, closing], 2, 5))
# plot_img(create_arr([img, thresh_green2_orig, thresh_green2, tconfident, tclosing, blur, thresh_green_orig, thresh_green, confident, closing], 2, 5), create_arr(['original', 'green', 'green + contrast', 'confident', 'final', 'blur', 'blurred green', 'blurred green + contrast', 'confident', 'final'], 2, 5))

# Finding unknown region
print('identifying unknown regions (those not classified as either foreground or background)')
unknown = cv.subtract(closing, tconfident)

# Marker labelling
print('marking connected components')
# ret, markers = cv.connectedComponents(sure_fg)
ret, markers = cv.connectedComponents(tconfident.astype(np.uint8))
# Add one to all labels so that sure background is not 0, but 1
markers = markers+1
# Now, mark the region of unknown with zero
markers[unknown==255] = 0

print('running the watershed algorithm')
markers = cv.watershed(img,markers)
# img[markers == -1] = [255,0,0]

# # finally, now that we have each pixel marked according to the region it belongs to
# print('finding polygons')
markers[markers == -1] = 1
markers -= 1

# should we save the segments as a mask or as bounding boxes?
if args.out.name.endswith('.npy'):
    np.save(args.out.name, markers)
elif args.out.name.endswith('.json'):
    # import extra required modules
    import json
    from imantics import Mask
    # create json structure
    cam_segments = {
        'flags': {},
        'shapes': [
            {
                'label': int(i),
                'line_color': None,
                'fill_color': None,
                'points': Mask(markers == i).polygons().points[0].tolist(),
                'shape_type': "polygon",
                'flags': {}
            }
            for i in filter(lambda x: x, np.unique(markers))
        ]
    }
    # write the json to a file
    with open(args.out.name, 'w') as out:
        json.dump(cam_segments, out)
else:
    sys.exit("Unsupported output file format.")
