import cv2
import numpy as np
from math import radians, cos, sin, sqrt
from helpers.GPSHelper import calcBearing, calcGPSDestination, distBetweenCoord

debugMode = False
#logger = logging.getLogger(__name__)

def debug(str):
    if debugMode:
        print(str)


class LandingPoint:
    def __init__(self, landingLat, landingLong, deriveLat, deriveLong):
        self.gpsLandingCoordinate = (landingLat, landingLong) #array of size 2
        self.gpsDeriveCoordinate = (deriveLat, deriveLong)


class Lakes:
    def __init__(self, lakeContour, lakeArea, resolution):
        self.lakeContour = lakeContour
        self.lakeArea = lakeArea
        self.resolution = resolution
        self.landingPoint = []
        self.gpsLandingPoint = []
        self.width, self.height = self.__getWidthHeight()
        self.landingList = []

    def __getWidthHeight(self):
        x1, y1 = self.lakeContour.min(axis=0)[0]
        x2, y2 = self.lakeContour.max(axis=0)[0]
        width = y2 - y1
        height = x2 - x1
        return width, height

    def __addSortLandingPoint(self, landingList, distanceOffset):
        points = []
        sortList = []
        maxLat = None
        minLat = None
        maxLong = None
        minLong = None
        addMorePoint = False

        if len(landingList) > 0 :

            maxLatLP = max(landingList, key=lambda item: item.gpsLandingCoordinate[0])
            minLatLP = min(landingList, key=lambda item: item.gpsLandingCoordinate[0])
            maxLongLP = max(landingList, key=lambda item: item.gpsLandingCoordinate[1])
            minLatLP = min(landingList, key=lambda item: item.gpsLandingCoordinate[1])

            maxLat = maxLatLP.gpsLandingCoordinate
            minLat = minLatLP.gpsLandingCoordinate
            maxLong = maxLongLP.gpsLandingCoordinate
            minLong = minLatLP.gpsLandingCoordinate

            points.append(maxLatLP)
            points.append(minLatLP)
            points.append(maxLongLP)
            points.append(minLatLP)

            #Remove the points near the maximal and minimal points
            for landingPoint in landingList:
                point = landingPoint.gpsLandingCoordinate
                if (
                distBetweenCoord(maxLong[0],maxLong[1], point[0], point[1]) > distanceOffset and
                distBetweenCoord(minLong[0],minLong[1], point[0], point[1]) > distanceOffset and
                distBetweenCoord(maxLat[0],maxLat[1], point[0], point[1]) > distanceOffset and
                distBetweenCoord(minLat[0],minLat[1], point[0], point[1]) > distanceOffset
                ):
                    sortList.append(landingPoint)

            addMorePoint = distBetweenCoord(maxLong[0],maxLong[1], minLong[0], minLong[1]) > distanceOffset or distBetweenCoord(maxLat[0],maxLat[1], minLat[0], minLat[1]) > distanceOffset

        #Delete the duplicate points
        points = list(set(points))

        return points, sortList, addMorePoint

    def getSortLandingPoint(self, maxDistance):
        points = []
        distanceOffset = maxDistance/2
        tmpPoints, newSortList, addMorePoint = self.__addSortLandingPoint(self.landingList, distanceOffset)
        points = points + tmpPoints

        while addMorePoint:
            tmpPoints, newSortList, addMorePoint = self.__addSortLandingPoint(newSortList, distanceOffset)
            points = points + tmpPoints

        #Delete the duplicate points
        points = list(set(points))
        return points

    def getContourPoint(self):
        points = []
        right = self.xCenter + (self.height/2)
        bottom = self.yCenter + (self.width/2)
        left = self.xCenter - (self.height/2)
        top = self.yCenter - (self.width/2)

        bottomRight = self.mapObject.xy2LatLon([right, bottom])
        bottomLeft  = self.mapObject.xy2LatLon([left, bottom])
        topRight    = self.mapObject.xy2LatLon([right, top])
        topLeft     = self.mapObject.xy2LatLon([left, top])
        center      = self.mapObject.xy2LatLon([self.xCenter, self.yCenter])

        points.append(center)
        points.append(bottomRight)
        points.append(bottomLeft)
        points.append(topRight)
        points.append(topLeft)

        return points

    # Find the contour of the water body
    def cropContour(self, mapObject):
        self.mapObject = mapObject
        x1, y1 = self.lakeContour.min(axis=0)[0]
        x2, y2 = self.lakeContour.max(axis=0)[0]
        self.xCenter = (x2 + x1) // 2
        self.yCenter = (y2 + y1) // 2
        self.centerPoint = mapObject.xy2LatLon([self.xCenter, self.yCenter])
        self.contourImage = self.mapObject.processed_im[y1:y2, x1:x2]
        self.lakeContour = self.lakeContour - [x1, y1]

    def xy2LatLon(self, point):
        # xc and yc are the center of the image of the lake in pixel
        # shape[0] is y and shape[1] is x at this moment... should be changed
        yc = self.contourImage.shape[0] // 2 + 1
        xc = self.contourImage.shape[1] // 2 + 1

        # https://www.movable-type.co.uk/scripts/latlong.html
        # Calculate the x,y in a cartesian plan
        yCart = yc - point[1]
        xCart = point[0] - xc
        debug("Cartesian: %s %s" % (xCart, yCart))

        # Calculate the bearing from the north
        bearing = calcBearing(xCart, yCart)

        # Calculate the distance between the lakeCenter and the point
        d = sqrt(yCart ** 2 + xCart ** 2) * self.resolution
        debug("d: %s" % d)

        # Calculate the gps coordinate of the point2
        lat2, long2 = calcGPSDestination(self.centerPoint, d/1000, bearing)
        debug("latlong %s %s" % (lat2, long2))
        return lat2, long2

    def findLandingPoint(self, weatherDict, expectedTime, chargingTime):
        landingPointList = []
        self.landingPoint[:] = []
        self.gpsLandingPoint[:] = []
        self.gpsDerivePoint = []

        timeIndex = weatherDict["time"].index(min(weatherDict["time"], key=lambda x: abs(x - expectedTime)))

        windDir = weatherDict["windDirection"][timeIndex]

        if (weatherDict["windDirection"][timeIndex] <= 90):
                windDir = -weatherDict["windDirection"][timeIndex] + 90
        else:
            windDir = -weatherDict["windDirection"][timeIndex] + 450

        deriveSpeed = weatherDict["windSpeed"][timeIndex] * 0.05
        distanceDeriveKm = deriveSpeed * (chargingTime/3600)
        # print("vector lenght : %f km    angle: %f"%(distanceDeriveKm, windDir))

        # Need to add sun force depending on the time of the year/day, variation of the charging time with cloud cover changing over time
        derive = deriveSpeed * chargingTime // self.resolution

        point2 = [int(derive * 1.0 * sin(radians(windDir - 10))), int(derive * 1.0 * cos(radians(windDir - 10)))]
        point3 = [int(derive * 1.0 * sin(radians(windDir + 10))), int(derive * 1.0 * cos(radians(windDir + 10)))]

        imax = self.contourImage.shape[0]
        jmax = self.contourImage.shape[1]
        lastJ = 0
        lastI = 0
        idetected = False
        #logger.debug('findLandingPoint..')
        iStep = min([100, max([5, int(imax/20)])])
        jStep = min([100, max([5, int(jmax/20)])])
        for i in range(0, imax, iStep):
            jdetected = False

            if not idetected or (idetected and i >= lastI+25):
                for j in range(0, jmax, jStep):
                    if not jdetected or (jdetected and j >= lastJ+25):
                        if (i + point2[0] >= 0 and j + point2[1] >= 0 and i + point3[0] >= 0 and j + point3[1] >= 0):
                            if i + point2[0] < imax and j + point2[1] < jmax and i + point3[0] < imax and j + point3[1] < jmax:
                                pointsAreInside = True
                            else:
                                pointsAreInside = False
                        else:
                            pointsAreInside = False
                        if (cv2.pointPolygonTest(self.lakeContour, (j, i), False) >= 0 and pointsAreInside):
                            point = np.array([[j, i], [j + point2[1], i + point2[0]], [j + point3[1], i + point3[0]]])
                            tempImage = np.copy(self.contourImage)
                            cv2.fillConvexPoly(tempImage, point, 0)

                            #Add a circle to assure that there are no land near the landing point
                            tempImage2 = np.copy(self.contourImage)
                            cv2.circle(tempImage2,(j, i), 10, 0, -1)

                            tempImage3 = np.copy(self.contourImage)


                            if (np.array_equal(tempImage, self.contourImage)) and (np.array_equal(tempImage2, self.contourImage)):
                                self.landingPoint.append([i, j])

                                # print("------------------------------------")
                                gpsLanding = self.xy2LatLon([j, i])
                                gpsDerive = self.xy2LatLon([j+point2[1], i+point2[0]])

                                self.landingList.append(LandingPoint(gpsLanding[0], gpsLanding[1], gpsDerive[0], gpsDerive[1]))

                                self.gpsLandingPoint.append(self.xy2LatLon([j, i]))
                                self.gpsDerivePoint.append(self.xy2LatLon([j+point2[1], i+point2[0]]))
                                # print("LandingPoint", self.xy2LatLon([j, i]))
                                # print("Derive point", self.xy2LatLon([j+point2[0], i+point2[1]]))

                                cv2.circle(tempImage2,(i, j), 10, 0, -1)
                                jdetected = True
                                idetected = True
                                lastJ = j
                                lastI = i

                                #To check the deriveVector
                                cv2.fillConvexPoly(self.contourImage, point, (122,122,122))
                                # cv2.imwrite("WaterBodiesImages/" + "vector.jpg", tempImage3)

        for lp in self.landingPoint:
            self.contourImage[lp[0], lp[1]] = 255

        cv2.imwrite("lakeRecognition/WaterBodiesImages/{},{}.jpg".format(self.centerPoint.lat, self.centerPoint.lon), self.contourImage)
        return self.landingList

    def getLandingPoint(self):
        return self.landingList

    def getLakeCenter(self):
        return self.centerPoint
