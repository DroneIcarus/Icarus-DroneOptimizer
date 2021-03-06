import configparser
import cv2
import numpy as np
from collections import namedtuple
from math import sin, cos, tan, atan, sinh, pi, log, degrees, radians
from urllib.request import urlopen
from helpers.urlsigner import sign_url

################### Config File ###################
config = configparser.ConfigParser()
config.read('config.ini')
# Please ensure that you are using a key and a secret:
# https://console.cloud.google.com/apis/api/static_maps_backend/staticmap
GMAPS_STATIC_API_KEY = config['gmaps_keys']['api']
GMAPS_STATIC_SECRETS = config['gmaps_keys']['secret']


################### Google Maps URL ###################
STATIC_MAP_URL = "https://maps.googleapis.com/maps/api/staticmap?"
GMAPS_PARAMS = "center={},{}&zoom={}&size={}x{}&scale={}&maptype={}&format=jpg-baseline"
# Style took from https://snazzymaps.com/style/138/water-only
GMAPS_STYLE_ONLY_WATER = "&style=element:label|geometry.stroke|visibility:off&style=feature:road|visibility:off&style=feature:administrative|visibility:off&style=feature:poi|visibility:off&style=feature:water|saturation:-100|invert_lightness:true&style=feature|element:labels|visibility:off"
#GMAPS_STYLE_ONLY_WATER = "&style=feature:administrative|visibility:off&style=feature:landscape|visibility:off&style=feature:poi|visibility:off&style=feature:road|visibility:off&style=feature:transit|visibility:off&style=feature:water|element:geometry|hue:0x002bff|lightness:-78"


################### Coordinate tuples ###################
Coordinate = namedtuple('Coordinate', ['lat', 'lon'])
MapCoordinate = namedtuple('MapCoordinate', ['x', 'y'])
TileCoordinate = namedtuple('TileCoordinate', ['xtile', 'ytile'])
ImagePixel = namedtuple('ImagePixel', ['x', 'y'])

################### Constants ###################
GMAPS_ZOOM = 14
GMAPS_IMAGE_SIZE_REFERENCE = ImagePixel(256, 256) # This is defined by Google Maps. NOT TO BE CHANGED.
GMAPS_IMAGE_SIZE = GMAPS_IMAGE_SIZE_REFERENCE     # The image size we want from google maps
MAP_TILES_SIZE = TileCoordinate(2 ** GMAPS_ZOOM, 2 ** GMAPS_ZOOM)
MAX_REQUEST_TRIES = 5


###################################################################
#
# Google Maps Static API communications functions
#
###################################################################


# Handle the Google Map request
# If specified, it can overwrites Google Maps copyright with the actual image
# Without doing so, recognizing the landing points will be much more difficult
# Beware... that's eating 2x more requests of our free Google Maps contract (which is 25 000/day)
def get_google_maps_image(coord, remove_copyright=True):
    base_url = gmaps_url_former(coord)

    # Make the request and save the image
    image = gmaps_request(base_url)

    if remove_copyright:
        # Eating 24 pixels on the bottom. For smaller images it can either be 14, 18 or 20... further analysis needed.
        pixelcoord = latlon_to_pixelcoord(coord)
        offset_coord = pixelcoord_to_latlon(ImagePixel(pixelcoord.x, pixelcoord.y + 24))

        offset_url = gmaps_url_former(offset_coord)
        offset_image = gmaps_request(offset_url)
        return remove_gmaps_copyright(image, offset_image)
    else:
        return image


# Form the URL and sign it
def gmaps_url_former(coord):
    # Creates the URL to fetch an image
    lat = str(coord.lat)
    lon = str(coord.lon)
    url = STATIC_MAP_URL + GMAPS_PARAMS.format(lat, lon, GMAPS_ZOOM, GMAPS_IMAGE_SIZE.x, GMAPS_IMAGE_SIZE.y, 1,
                                               "roadmap") + GMAPS_STYLE_ONLY_WATER + "&key=" + GMAPS_STATIC_API_KEY

    # Signs the url with private key
    url = sign_url(url, GMAPS_STATIC_SECRETS)
    return url


# Replace Google Maps copyright with associated image part
def remove_gmaps_copyright(image, offset_image):
    # Conversion to numpy/opencv arrays
    image = cv2.imdecode(np.asarray(bytearray(image), dtype="uint8"), cv2.IMREAD_COLOR)
    offset_image = cv2.imdecode(np.asarray(bytearray(offset_image), dtype="uint8"), cv2.IMREAD_COLOR)

    # We are removing the copyright part and replace it with its associated part
    adjusted_im = np.concatenate((image[0:-24, 0:], offset_image[-48:-24, 0:]), axis=0)
    return adjusted_im


# Make the actual request to Google Map Static API
def gmaps_request(url, try_nb=MAX_REQUEST_TRIES):
    response = urlopen(url)

    if response.status == 200:
        return response.read()

    elif response.status in range(500, 599):
        # 5xx Server Error
        # Try up to <try_nb> times
        if try_nb > 0:
            gmaps_request(url, try_nb-1)
        return None

    else:
        # For every other HTTP code... do nothing
        return None

###################################################################
#
# Conversion functions for coordinates
#
###################################################################


# Convert (latitude,longitude) to a Coordinate tuple
def latlon_to_coordinate(lat, lon):
    return Coordinate(lat, lon)


# Convert (xtile, ytile) to a Tile Coordinate tuple
def xytile_to_tilecoordinate(xtile, ytile):
    return TileCoordinate(xtile, ytile)


# Convert (xpixel, ypixel) to Map Coordinate tuple
def xypixel_to_mapcoordinate(xpixel, ypixel):
    return MapCoordinate(xpixel, ypixel)
###################################################################
#
# Getters functions for this file constants/variables
#
###################################################################


# Return the zoom level
def get_zoom():
    return GMAPS_ZOOM


# Return the total number of tiles horizontally and vertically
def get_tile_size():
    return MAP_TILES_SIZE


###################################################################
#
# Equations based on latitude and longitude
#
###################################################################


# Perform the mercator projection. This is used to convert (latitude,longitude) to a point on the map
def mercator_projection(coord, tile_size=GMAPS_IMAGE_SIZE_REFERENCE):
    # For references, please refer to: http://mathworld.wolfram.com/MercatorProjection.html
    # and https://wiki.openstreetmap.org/wiki/Slippy_map_tilenames#Implementations
    # Google offers an alternative: https://developers.google.com/maps/documentation/javascript/examples/map-coordinates
    return MapCoordinate(tile_size.x * (coord.lon/360 + 0.5),
                         tile_size.y/2 * (1 - log( tan(radians(coord.lat)) + 1/cos(radians(coord.lat)) ) / pi))


# Return the tile (x,y) associated with the provided coordinate (lat,lon)
def latlon_to_tile(coord, zoom=GMAPS_ZOOM):
    n = 2 ** zoom
    xtile = int((0.5 + coord.lon/360) * n)
    ytile = int((1 - log(tan(radians(coord.lat)) + (1/cos(radians(coord.lat)))) / pi) / 2 * n)
    return TileCoordinate(xtile, ytile)


# Return the pixel coordinate associated with the provided coordinate (lat,lon)
def latlon_to_pixelcoord(coord, zoom=GMAPS_ZOOM):
    world_coord = mercator_projection(coord)
    return ImagePixel(round(world_coord.x*(2**zoom)), round(world_coord.y*(2**zoom)))


###################################################################
#
# Equations to return to variables based on latitude and longitude
#
###################################################################


# Perform the inverse mercator projection which does a conversion from map coordinate to (lat,lon)
def inverse_mercator_projection(map_coord, tile_size=GMAPS_IMAGE_SIZE_REFERENCE):
    # For references, please refer to: http://mathworld.wolfram.com/Gudermannian.html
    # and https://wiki.openstreetmap.org/wiki/Slippy_map_tilenames#Implementations
    return Coordinate(degrees(atan(sinh(pi * (1 -2 * map_coord.y/tile_size.y)))),
                      (360 * map_coord.x / tile_size.x) - 180)


# Return the coordinate (lat,lon) associated with the provided tile (x,y)
def tile_to_latlon(tilecoord, zoom=GMAPS_ZOOM):
    n = 2.0 ** zoom
    lon_deg = tilecoord.xtile / n * 360.0 - 180.0
    lat_deg = degrees(atan(sinh(pi * (1 - 2 * tilecoord.ytile / n))))
    return Coordinate(lat_deg, lon_deg)


# Return the (lat,lon) associated with the provided pixel coordinate
def pixelcoord_to_latlon(pixelcoord, zoom=GMAPS_ZOOM):
    map_coord = MapCoordinate(pixelcoord.x/(2**zoom), pixelcoord.y/(2**zoom))
    return inverse_mercator_projection(map_coord)


###################################################################
#
# Tile numbering functions. Useful for database communication.
#
###################################################################

# Return the tile no from the tile coordinate (x,y)
def tile_no_by_tile_coord(tile_coord, max_tile_size=MAP_TILES_SIZE):
    # Operate using Google Maps tile size of 256x256 px
    # The total number of tiles is calculated by:  2 ** (zoom*2)
    # Eg.: For a zoom of 14; 16384 * 16384 = 268435456 tiles
    # Hence no tile_no should exceed this number
    return tile_coord.xtile + tile_coord.ytile * max_tile_size.xtile


# Return the tile coordinate(x,y) based from the tile no
def tile_coord_by_tile_no(tile_no, max_tile_size=MAP_TILES_SIZE):
    # Operate using Google Maps tile size of 256x256 px
    ytile, xtile = divmod(tile_no, max_tile_size.xtile)
    return xytile_to_tilecoordinate(xtile, ytile)


if __name__ == "__main__":
    # NOTE: Google operates Maps using tiles of 256x256 pixels
    c = Coordinate(44.1644712, -74.3818805)
    b = latlon_to_tile(c, GMAPS_ZOOM)
    b = b._replace(xtile=b.xtile + 1)
    b = tile_to_latlon(b, GMAPS_ZOOM)

    print("{} , {}".format(b.lat, b.lon))

    c = get_google_maps_image(b, True)

    # d = np.asarray(bytearray(c), dtype="uint8")
    # d = cv2.imdecode(d, cv2.IMREAD_COLOR)

    cv2.imwrite('/tmp/test1000.jpg', c)

