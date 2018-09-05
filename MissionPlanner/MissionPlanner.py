import numpy
import sys, os
import time
import csv
import logging
from math import radians, degrees, cos, sin, asin, atan, atan2, sqrt
import matplotlib.pyplot as plt
from TSP.tsp_christofides import CreateGraph, DrawGraph, christofedes
# from graphConstruction.CreateNode import node_create,node_set_neighbours
from lakeRecognition.mapClass import Map
from helpers.WeatherHelper import getOpenWeather
from helpers.GPSHelper import distBetweenCoord, calcMetereologicalDegree, calcVectorDegree
from aStar.aStar import aStar
from aStar.Node import Node
from operator import itemgetter
from MissionPlanner.MissionPlan import MissionItem, build_simple_mission_item

logger = logging.getLogger(__name__)

class Weather:
    def __init__(self, latitude, longitude, time, windDirection, windSpeed, cloudCover):
        self.__latitude = latitude
        self.__longitude = longitude
        self.__checkLatitudeLongitude()

        self.time = time
        self.windDirection = windDirection
        self.windSpeed = windSpeed
        self.cloudCover = cloudCover

    def __checkLatitudeLongitude(self):
        if self.__latitude == None or self.__longitude == None:
            print("ERROR - Coordinates for generating the weather point is not valid")
            sys.exit()

class WeatherList:
    def __init__(self, latitude, longitude):
        self.__latitude = latitude
        self.__longitude = longitude
        self.__checkLatitudeLongitude()
        self.__longWeather = getOpenWeather(self.__latitude, self.__longitude);

    def __checkLatitudeLongitude(self):
        if self.__latitude == None or self.__longitude == None:
            print("ERROR - Coordinates for generating the weatherList is not valid")
            sys.exit()

    def __checkExpectedTime(self, expectedTime, timeIndex):
        #86400 is equivalent to one day
        if(abs(self.__longWeather["time"][timeIndex] - expectedTime) > 86400):
            print("No precise weather near the expected time...")
            sys.exit()

    def getWeather(self, expectedTime):
        timeIndex = self.__longWeather["time"].index(min(self.__longWeather["time"], key=lambda x: abs(x -expectedTime)))
        self.__checkExpectedTime(expectedTime, timeIndex)
        return Weather(self.__latitude, self.__longitude, self.__longWeather["time"][timeIndex], self.__longWeather["windDirection"][timeIndex],
                        self.__longWeather["windSpeed"][timeIndex], self.__longWeather["cloudCover"][timeIndex])

    def getWindSpeed(self, expectedTime):
        timeIndex = self.__longWeather["time"].index(min(self.__longWeather["time"], key=lambda x: abs(x -expectedTime)))
        self.__checkExpectedTime(expectedTime, timeIndex)
        return self.__longWeather["windSpeed"][timeIndex]

    def getWindDirection(self, expectedTime):
        timeIndex = self.__longWeather["time"].index(min(self.__longWeather["time"], key=lambda x: abs(x -expectedTime)))
        self.__checkExpectedTime(expectedTime, timeIndex)
        return self.__longWeather["windDirection"][timeIndex]

    def getCloudCover(self, expectedTime):
        timeIndex = self.__longWeather["time"].index(min(self.__longWeather["time"], key=lambda x: abs(x -expectedTime)))
        self.__checkExpectedTime(expectedTime, timeIndex)
        return self.__longWeather["cloudCover"][timeIndex]

class MissionPlanner(object):
    """docstring for ."""
    def __init__(self, plan, name):
        super(MissionPlanner, self).__init__()
        self.missionName = name
        self.missionPlan = plan
        gpsPointsList = plan.get_mission().get_waypoints()
        self.maximalMapPoint = self.__getMaximalMapPoint(gpsPointsList)
        self.nbMissionPoint = len(gpsPointsList)
        self.initialMissionItemList = plan.get_mission().get_missionitems()

        self.timeInMission = time.time()
        self.timeSpentInMission = 0
        self.droneSpeed = 40 #km/h

        self.weather = WeatherList(self.initialMissionItemList[0].get_x(), self.initialMissionItemList[0].get_y())
        currentWeather = self.weather.getWeather(self.timeInMission)

        self.distanceMatrix = self.__getDistanceMatrix()
        self.__missionIndex = 0

        self.__timeAutonomy = 15 #minute
        self.__currentAutonomy = self.__timeAutonomy
        self.__ChargingTime = 60 #minute

        #For the missionBuilders
        self.finalMissionItemList = [];
        #For the csv export
        self.resultingWay = [['latitude','longitude','name']]

        self.exportPath = "export/"

    def getDroneDirection(self, mItem1, mItem2):
        return calcMetereologicalDegree(mItem1.get_x(), mItem1.get_y(), mItem2.get_x(), mItem2.get_y())

    def getDroneSpeed(self):
        return self.droneSpeed

    def getWindDirection(self):
        return self.weather.getWindDirection(self.timeInMission)

    def getWindSpeed(self):
        return self.weather.getWindSpeed(self.timeInMission)

    def getDroneSpeedAfterWindEffect(self, mItem1, mItem2):
        ddrone = self.getDroneDirection(mItem1, mItem2)
        dwind = self.getWindDirection()
        speedWind = self.getWindSpeed()
        deltaDirection = abs(ddrone - dwind)
        windEffect = speedWind*cos(radians(deltaDirection))

        if deltaDirection > 90:
                speedDrone = self.droneSpeed - windEffect
        else:
                speedDrone = self.droneSpeed + windEffect

        # print("ddrone", ddrone)
        # print("dwind", dwind)
        # print("deltaDirection", deltaDirection)
        # print("speedWind", speedWind)
        # print("windEffect", windEffect)
        # print("speedDrone", speedDrone)

        if speedDrone < 10:
            logger.error("The wind is too strong to execute the mission")
            sys.exit("ERROR: The wind is too strong to execute the mission")
        return speedDrone

    def getTimeToFly(self, mItem, mItem2):
        droneSpeed = self.getDroneSpeedAfterWindEffect(mItem, mItem2)
        distanceToFly = mItem.distanceTo(missionItem=mItem2)
        timeToFly = (distanceToFly / droneSpeed) * 60
        return timeToFly

    #Calculate the distance matrix
    def __getDistanceMatrix(self):
        # TODO: Should become a cost matrix when we will find a way to evaluate a cost
        distanceMatrix = numpy.zeros((self.nbMissionPoint, self.nbMissionPoint))
        i = 0
        for mItem in self.initialMissionItemList:
            j = 0
            for mItem2 in self.initialMissionItemList:
                distanceMatrix[i][j] = self.getTimeToFly(mItem, mItem2)
                j+=1
            i+=1
        #Assign a very low cost between the first and last node to be sure that there are aside because we want to have a start and a end
        distanceMatrix[0][self.nbMissionPoint-1] = 0.000001
        distanceMatrix[self.nbMissionPoint-1][0] = 0.000001
        # logger.debug(distanceMatrix)
        return distanceMatrix

    def getMissionPointOrder(self):
        # TODO: Maybe... create a fonction for this
        # TODO: Find a way to attribute a very low or null cost between the start node and the end node
        G = CreateGraph(matrix = self.distanceMatrix)
        pos = DrawGraph(G,'black')
        opGraph, nodeOrder = christofedes(G, pos)

        #Need to correct the order if not true
        if nodeOrder[0] != 0 or nodeOrder[-1] !=  self.nbMissionPoint-1:
            #Need to inverse the order if true
            if nodeOrder[0] == 0 and nodeOrder[1] == self.nbMissionPoint-1:
                i = 1
                while 2*i < self.nbMissionPoint:
                    tmp = nodeOrder[i]
                    nodeOrder[i] = nodeOrder[-i]
                    nodeOrder[-i] = tmp
                    i=i+1

        #If the nodeOrder is not correct, we need to stop the program
        if nodeOrder[0] != 0 or nodeOrder[-1] !=  self.nbMissionPoint-1:
            logger.warning("Order of node: %o", nodeOrder)
            logger.warning("The node order is not good...")
            sys.exit("ERROR: MissionPlanner::getMissionPointOrder, the node order is incorrect.")

        # logger.debug("Order of node: ", nodeOrder)
        return nodeOrder

    #Return a graph showing the link and graph of the result after running the tsp algorithm
    def getMissionPointGraph(self):
        # TODO: Maybe... create a fonction for this
        # TODO: Find a way to attribute a very low or null cost between the start node and the end node
        G = CreateGraph(matrix = self.distanceMatrix)
        plt.figure(1)
        pos = DrawGraph(G,'black')
        opGraph, nodeOrder = christofedes(G, pos)
        plt.figure(2)
        pos1 = DrawGraph(opGraph,'r')
        plt.show()

    #Retourne une liste de paire de coordonnees GPS equivalent au debut et a la fin de petite mission
    #Exemple si l'ordre des points de mission est A, C B - La liste retournee sera [(A,C),(C,B)]
    def __getPairedMissionPoints(self):
        result = []
        nodeOrder  = self.getMissionPointOrder()
        i = 0
        for index in nodeOrder:
            if i < len(nodeOrder) - 1:
                nextIndex = nodeOrder[i + 1]
                result.append((self.initialMissionItemList[index], self.initialMissionItemList[nextIndex]))
            i=i+1
        return result

    #Delete the lake with no landing point
    def __sortLakeList(self, lakeList):
        ToDelete = []
        # TODO: Mettre dans une seule for loop
        for i in range(len(lakeList)):
            if(len(lakeList[i].getLandingPoint())<=0):
                ToDelete.append(i)

        for i in range(len(ToDelete)):
            del lakeList[ToDelete[i]-i]
        if len(lakeList) == 0:
            logger.error("No point to land between the mission points so the mission is probably impossible")
            sys.exit("ERROR: No point to land between the mission points. The mission is probably impossible.")

    def getLandinggPointNumberByLake(self):
        count = 0
        for i in range(len(lakeList)):
            count = len(lakeList[i].getLandingPoint()) + count
            logger.info("landingPoints %i",len(lakeList[i].getLandingPoint()))
        logger.info("Count total: %i",count)
        # logger.debug("Lon s",lakeList[0].getLandingPoint()[0][0][0])
        # logger.debug("Lat s",lakeList[0].getLandingPoint()[0][0][1])
        # logger.debug("Lon e",lakeList[len(lakeList)-1].getLandingPoint()[0][0][0])
        # logger.debug("Lat e",lakeList[len(lakeList)-1].getLandingPoint()[0][0][1])
        return count

    #Retourne la liste de lacs avec leurs landing points se trouvant dans la totalité des limites de la mission
    def __getTotalLakeList(self, minLat, maxLat, minLong, maxLong):
        lakeList = []

        #Lake detection
        map1 = Map(str(minLat),str(minLong), str(maxLat), str(maxLong))
        imageProcessed = map1.satImageProcess(map1.imageAdded)
        imageWithContour = map1.findLakeContour(imageProcessed,map1.imageAdded,lakeList)

        [lake.cropContour(imageProcessed,map1) for lake in lakeList]

        weather = getOpenWeather(map1.verticalCenter,map1.horizontalCenter)

        [lake.findLandingPoint(weather,int(time.time())) for lake in lakeList]

        self.__sortLakeList(lakeList)

        self.__exportLakesCenter(lakeList)
        self.__exportLakesContour(lakeList)
        self.__exportLakesSortPoint(lakeList)
        self.__exportLakesLandingPoint(lakeList)

        return lakeList

    #Retourne une liste de lacs avec leurs landing points se trouvant entre les 2 points GPS
    def __getLakeList(self, gpsPoint1, gpsPoint2):
        lakeList = []

        #Lake detection
        map1 = Map(str(gpsPoint1.get_x()),str(gpsPoint1.get_y()), str(gpsPoint2.get_x()), str(gpsPoint2.get_y()))
        imageProcessed = map1.satImageProcess(map1.imageAdded)
        imageWithContour = map1.findLakeContour(imageProcessed,map1.imageAdded,lakeList)

        [lake.cropContour(imageProcessed,map1) for lake in lakeList]

        weather = getOpenWeather(map1.verticalCenter,map1.horizontalCenter)

        [lake.findLandingPoint(weather,int(time.time())) for lake in lakeList]
        self.__sortLakeList(lakeList)

        self.__exportLakesCenter(lakeList)
        self.__exportLakesContour(lakeList)
        self.__exportLakesSortPoint(lakeList)
        self.__exportLakesLandingPoint(lakeList)

        return lakeList

    # nodeId, distanceEnd,gpsLandingPoint, neighbors
    def node_create(self, lakeList, missionItemStart, missionItemEnd, distanceMax):
        allNodes = {}

        # End landing point
        missionItemEnd.setID('end')
        allNodes['end'] = missionItemEnd

        # Start landing point
        missionItemStart.setID('start')
        # missionItemStart.setDistanceEnd(missionItemStart.distanceTo(lat=missionItemEnd.get_x(), long=missionItemEnd.get_y()))
        missionItemStart.setDistanceEnd(self.getTimeToFly(missionItemStart, missionItemEnd))
        allNodes['start'] = missionItemStart

        for x in range(0, len(lakeList)):
            gpsLandingPoints = lakeList[x].getSortLandingPoint(self.droneSpeed*(distanceMax/60))

            for y in range(0, len(gpsLandingPoints)):
                missionItem = MissionItem(build_simple_mission_item(gpsLandingPoints[y][0], gpsLandingPoints[y][1],'lac_id:' + str(x) + ':' + str(y)))
                missionItem.setID('lac_id:' + str(x) + ':' + str(y))
                # missionItem.setDistanceEnd(missionItem.distanceTo(lat=missionItemEnd.get_x(), long=missionItemEnd.get_y()))
                missionItem.setDistanceEnd(self.getTimeToFly(missionItem, missionItemEnd))
                allNodes['lac_id:' + str(x) + ':' + str(y)] = missionItem

        return allNodes

    def node_set_neighbours(self, allNodes, distanceMax):
        nodes = allNodes.values()
        for node1 in nodes:
            for node2 in nodes:
                # distance = node1.distanceTo(missionItem=node2)
                distance = self.getTimeToFly(node1, node2)
                if (distance < distanceMax):
                        neighbors = list(node1.neighbors.items())
                        # node1.AddNeighbor(node2.nodeId, node1.distanceTo(missionItem=node2))
                        node1.AddNeighbor(node2.nodeId, self.getTimeToFly(node1, node2))

    def __getAStarNodes(self, start, end, lakeList):
        gpsCoordinateStart = start
        gpsCoordinateEnd = end
        allNodes = self.node_create(lakeList, gpsCoordinateStart, gpsCoordinateEnd, self.__timeAutonomy)
        self.node_set_neighbours(allNodes, self.__timeAutonomy)
        return allNodes

    def __runAStar(self, start, end, lakeList):
        nodeList = self.__getAStarNodes(start, end, lakeList)
        logger.info("Starting aStar process...");
        logger.info("Nombre de nodes pour aStar: %i", len(nodeList))


        success, aStarResult = aStar(nodeList)

        #transform the aStar result into nodes
        result = []
        for value in aStarResult:
            result.append(nodeList[value])

        return success, result

    #Export a csv file with the latitude and longitude of the center of each lake detected between a pair of mission point
    def __exportLakesCenter(self, lakeList):
        logger.debug("Exporting lakes center...")
        toExport = [['latitude','longitude','name']]
        i=0
        for lake in lakeList:
            toExport.append([lake.centerPoint[0], lake.centerPoint[1], i])
            i = i + 1

        fileName = self.exportPath + self.missionName + "_lakesCenter_" + str(self.__missionIndex) + ".csv"
        with open(fileName, 'w') as f:
            writer = csv.writer(f)
            writer.writerows(toExport)
        logger.debug("Exporting done!")

    def __exportLakesContour(self, lakeList):
        logger.debug("Exporting lakes contour...")
        toExport = [['latitude','longitude','name']]
        i=0
        for lake in lakeList:
            for point in lake.getContourPoint():
                toExport.append([point[0], point[1], i])
                pass
            i = i + 1

        fileName = self.exportPath + self.missionName + "_lakesContours_" + str(self.__missionIndex) + ".csv"
        with open(fileName, 'w') as f:
            writer = csv.writer(f)
            writer.writerows(toExport)
        logger.debug("Exporting done!")

    def __exportLakesSortPoint(self, lakeList):
        logger.debug("Exporting lakes sort point...")
        toExport = [['latitude','longitude','name']]
        i=0
        for lake in lakeList:
            for point in lake.getSortLandingPoint(self.droneSpeed*(self.__timeAutonomy/60)):
                toExport.append([point[0], point[1], i])
                pass
            i = i + 1

        fileName = self.exportPath + self.missionName + "_lakesSortPoint_" + str(self.__missionIndex) + ".csv"
        with open(fileName, 'w') as f:
            writer = csv.writer(f)
            writer.writerows(toExport)
        logger.debug("Exporting done!")

    def __exportLakesLandingPoint(self, lakeList):
        logger.debug("Exporting lakes landing points...")
        toExport = [['latitude','longitude','name']]
        i=0
        for lake in lakeList:
            for point in lake.getLandingPoint():
                toExport.append([point[0], point[1], i])
                pass
            i = i + 1

        fileName = self.exportPath + self.missionName + "_lakesLandingPoint_" + str(self.__missionIndex) + ".csv"
        with open(fileName, 'w') as f:
            writer = csv.writer(f)
            writer.writerows(toExport)
        logger.debug("Exporting done!")

    def __findOptimizedChargingPoint(self, start, end, lakeList):
        nearestPoint = [start.get_x(), start.get_y()]
        nearestDist = 99999
        if len(lakeList) != 0:
            for lake in lakeList:
                for landingPoint in lake.gpsLandingPoint:
                    # distStart = distBetweenCoord(landingPoint[0], landingPoint[1], start.get_x(), start.get_y())
                    distEnd = distBetweenCoord(landingPoint[0], landingPoint[1], end.get_x(), end.get_y())
                    landingMissionPoint = MissionItem(build_simple_mission_item(landingPoint[0], landingPoint[1], "charging"))
                    landingMissionPoint.setID('charging')
                    timeToStart = self.getTimeToFly(landingMissionPoint, start)
                    # timeToEnd = self.getTimeToFly(landingMissionPoint, end)
                    # if distStart < self.__charge and distEnd < nearestDist:
                    if timeToStart < self.__currentAutonomy and distEnd < nearestDist:
                        nearestPoint = landingPoint
                        nearestDist = distEnd
                        pass
                pass
        return nearestPoint

    def __getMaximalMapPoint(self, gpsPointsList):
        points = []
        if len(gpsPointsList) > 1 :
            maxLat = max(gpsPointsList,key=itemgetter(0))[0]
            minLat = min(gpsPointsList,key=itemgetter(0))[0]
            maxLong = max(gpsPointsList,key=itemgetter(1))[1]
            minLong = min(gpsPointsList,key=itemgetter(1))[1]

            points.append(minLat)
            points.append(maxLat)
            points.append(minLong)
            points.append(maxLong)
        else:
            logger.error("Not enough missions points")
            sys.exit("ERROR: Not enough missions points.")

        return points

    def __addMissionItem(self, missionItem):
        if missionItem.getID() == 'charging':
            newItemWait = MissionItem(build_simple_mission_item(None, None, 'wait'))
            newItemTakeOff = MissionItem(build_simple_mission_item(missionItem.get_x(), missionItem.get_y(), 'takeoff'))
            self.finalMissionItemList.append(missionItem)
            self.resultingWay.append([missionItem.get_x(), missionItem.get_y(), missionItem.get_name()])

            self.finalMissionItemList.append(newItemWait)
            self.resultingWay.append([newItemWait.get_x(), newItemWait.get_y(), newItemWait.get_name()])

            self.finalMissionItemList.append(newItemTakeOff)
            self.resultingWay.append([newItemTakeOff.get_x(), newItemTakeOff.get_y(), newItemTakeOff.get_name()])
        else:
            self.finalMissionItemList.append(missionItem)
            self.resultingWay.append([missionItem.get_x(), missionItem.get_y(), missionItem.get_name()])
        pass

    def __createAndAddMissionItem(self, gpsX, gpsY, idType):
        newItem = MissionItem(build_simple_mission_item(gpsX, gpsY, idType))
        newItem.setID(idType)
        self.__addMissionItem(newItem)
        pass

    def __compileAStarResult(self, result, lakeList):
        start = result[0]
        end = result[len(result)-1]

        i=1
        lastPointVisited = start

        while result[i] != end:
            # dist = distBetweenCoord(lastPointVisited.get_x(), lastPointVisited.get_y(), result[i].get_x(), result[i].get_y())
            timeToFly = self.getTimeToFly(lastPointVisited, result[i])
            # self.__charge = self.__charge - dist
            self.__currentAutonomy = self.__currentAutonomy - timeToFly
            chargingPoint = self.__findOptimizedChargingPoint(result[i], result[i+1], lakeList)
            chargingPoint = MissionItem(build_simple_mission_item(chargingPoint[0], chargingPoint[1], "charging"))
            chargingPoint.setID('charging')

            #Reset the autonomy
            self.__currentAutonomy = self.__timeAutonomy

            if(distBetweenCoord(chargingPoint.get_x(), chargingPoint.get_y(), end.get_x(), end.get_y()) < 0.300):
                #break to assure to not add the end 2 times and we always want to add the real end to keep all the missionItem configuration
                break
            else:
                lastPointVisited = chargingPoint
                self.__addMissionItem(lastPointVisited)
            i = i + 1
        self.__addMissionItem(end)

    def run(self):
        #Plan a mission between each pairedPoint
        pairedMissionPoint = self.__getPairedMissionPoints()

        #Add the starting missionPoint
        self.__addMissionItem(pairedMissionPoint[0][0])

        #Get all the landing point
        lakeList = self.__getTotalLakeList(self.maximalMapPoint[0], self.maximalMapPoint[1], self.maximalMapPoint[2], self.maximalMapPoint[3])

        for pairedPoint in pairedMissionPoint:
            i=0
            distanceBetweenPoints = pairedPoint[0].distanceTo(pairedPoint[1])
            timeToFlyBetweenPoints = self.getTimeToFly(pairedPoint[0], pairedPoint[1])

            #Only get the lakes if we can't go directly to the next point
            if timeToFlyBetweenPoints > self.__currentAutonomy:
            # if distanceBetweenPoints > self.__charge:
                startPoint = pairedPoint[0]
                if self.__currentAutonomy < self.__timeAutonomy:
                    #Find the optimize charging points
                    chargingPoint = self.__findOptimizedChargingPoint(pairedPoint[0], pairedPoint[1], lakeList)

                    self.__createAndAddMissionItem(chargingPoint[0], chargingPoint[1], "charging")

                    #Reset the autonomy
                    self.__currentAutonomy = self.__timeAutonomy

                    #After the charging, execute aStar from the charging point
                    startPoint = MissionItem(build_simple_mission_item(chargingPoint[0],chargingPoint[1],"start"))
                    startPoint.setID('start')

                #Once we have every findLandingPoint and the start point and end point we can generate a graph for A* and run it
                success, result = self.__runAStar(startPoint, pairedPoint[1], lakeList)

                if success:
                    self.__compileAStarResult(result, lakeList)
                else:
                    logger.error("The last mission point wasn't reach... So the mission is probably impossible")
                    sys.exit("ERROR: The last mission point wasn't reach. The mission is probably impossible.")

            else:
                # self.__charge = self.__charge - distanceBetweenPoints
                self.__currentAutonomy = self.__currentAutonomy - timeToFlyBetweenPoints
                #Add directly the end point
                pairedPoint[1].setID('end')
                self.__addMissionItem(pairedPoint[1])

            self.missionPlan.mission.set_missionitems2(self.finalMissionItemList)
            self.__missionIndex = self.__missionIndex + 1

            #Use to debug when the mission is not completly done
            partialMissionFileName = self.exportPath + 'partialMission_' + str(self.__missionIndex) + '.csv'
            with open(partialMissionFileName, 'w') as f:
                writer = csv.writer(f)
                writer.writerows(self.resultingWay)

        with open(self.exportPath + 'completeMission.csv', 'w') as f:
            writer = csv.writer(f)
            writer.writerows(self.resultingWay)