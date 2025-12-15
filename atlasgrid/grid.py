# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QVariant
from qgis.core import Qgis, QgsProject, QgsVectorLayer, QgsFeature, QgsFeatureRequest, QgsExpression, QgsMessageLog, \
                      QgsField, QgsRectangle, QgsGeometry, QgsVector, QgsLayoutMeasurement, QgsLayoutMeasurementConverter, QgsCoordinateReferenceSystem
from qgis import processing

class GridCreator():
    feedback = None
    
    def __init__(self):
        pass

    def setCRS(self,crs):
        self.crs = crs

    def setFeedback(self,feedback):
        self.feedback = feedback
        return
    
    def calcGridMetrics(self,mapScale,extent,atlasCellSize,horizOverlap,vertOverlap):
        if self.feedback:
            self.feedback.pushInfo("Calculating grid metrics")
        # Create a measurement converter
        converter = QgsLayoutMeasurementConverter()

        # Convert dimensions to meters
        width_map_units = converter.convert(QgsLayoutMeasurement(atlasCellSize.width(), atlasCellSize.units()), Qgis.LayoutUnit.Meters).length()
        height_map_units = converter.convert(QgsLayoutMeasurement(atlasCellSize.height(), atlasCellSize.units()), Qgis.LayoutUnit.Meters).length()

        # Calculate the real-world dimensions
        rwWidth = width_map_units * mapScale
        rwHeight = height_map_units * mapScale
        rwWidthNet = width_map_units * ((100-horizOverlap)/100) * mapScale
        rwHeightNet = height_map_units * ((100-vertOverlap)/100) * mapScale

        # Calculate number of rows and columns
        rwDimensions = (rwWidth,rwHeight,rwWidthNet,rwHeightNet)
        cols = int((extent.width()-rwWidth) / rwWidthNet) + 2
        rows = int((extent.height()-rwHeight) / rwHeightNet) + 2
        nRowsAndCols = (rows,cols)
        
        # Adjust extent, so that the grid is centered
        adjustX = -(rwWidth + (cols-1) * rwWidthNet - extent.width()) / 2
        adjustY = (rwHeight + (rows-1) * rwHeightNet - extent.height()) / 2
        gridExtent = extent + QgsVector(adjustX, adjustY)
        
        return (rwDimensions,nRowsAndCols,gridExtent)


    def createGrid(self,mapScale,extent,rwDim,nRowsAndCols,deleteNonIntersecting,aoiLayer):
        if self.feedback:
            self.feedback.pushInfo("Creating grid")
        
        # create layer
        gridLayer = QgsVectorLayer("Polygon?crs={}".format(self.crs), 'AtlasGrid', "memory")

        fieldName = 'cellname'
        field = QgsField(fieldName, QVariant.String)
        numfield = QgsField('cellnum', QVariant.Int)
        disjoint_numfield = QgsField('dj_cellnum', QVariant.Int)
        gridLayer.dataProvider().addAttributes([field,numfield,disjoint_numfield])
        gridLayer.updateFields()

        # calculate start rectangle as upper leftmost rectangle
        x = extent.xMinimum()
        y = extent.yMaximum() - rwDim[1]
        prefix = ''
        colname = 'A'
        rownum = 1

        gridLayer.startEditing()

        # generate the net
        for i in range(0,nRowsAndCols[0]):
            for j in range(0,nRowsAndCols[1]):
                rectangle = QgsRectangle(x, y, x + rwDim[0], y + rwDim[1])
                cellname = "{}{}{}".format(prefix,colname,str(rownum))
                feat = QgsFeature(gridLayer.fields())
                feat.setAttribute(fieldName, cellname)
                feat.setGeometry(QgsGeometry.fromRect(rectangle))
                gridLayer.dataProvider().addFeatures([feat])

                x += rwDim[2]
                if colname < 'Z':
                    colname = chr(ord(colname)+1)
                else:
                    if prefix == '':
                        prefix = 'A'
                    else:
                        prefix = chr(ord(prefix)+1)
                    colname = 'A'

            x = extent.xMinimum()
            y -= rwDim[3]
            rownum += 1
            colname = 'A'
            prefix = ''

        # Check for non-intersecting cells if user has chosen to do so
        if deleteNonIntersecting:
            toBeDeleted = self.identifyCellsToDelete(gridLayer,aoiLayer)
        else:
            toBeDeleted = []
        
        # Delete cells not intersecting and number the remaining
        n = 0
        for f in gridLayer.getFeatures():
            if f["cellname"] in toBeDeleted:
                gridLayer.deleteFeature(f.id())
            else:
                n += 1
                f["cellnum"] = n
                if not deleteNonIntersecting:   
                    f["dj_cellnum"] = n

                gridLayer.updateFeature(f)

        gridLayer.commitChanges()

        # Calculate disjoint cell numbers
        if deleteNonIntersecting:
            self.calculateDisjointCellNums(gridLayer)
        
        return gridLayer

    def calculateDisjointCellNums(self,grid):
        QgsMessageLog.logMessage("Calculating disjoint cell numbers", "AtlasGrid", Qgis.Info)
        # Dissolve grid to get disjoint polygons
        alg_params = {'INPUT':grid,
                      'FIELD':[],
                      'SEPARATE_DISJOINT':True,
                      'OUTPUT':'TEMPORARY_OUTPUT'
                      }
        merged = processing.run("native:dissolve", alg_params, feedback=self.feedback)['OUTPUT']

        # Assign an ID to every disjoint polygon and calculate the min_x and max_y of the northwest corner - store this as tuples in a list
        QgsMessageLog.logMessage("Assigning IDs to disjoint polygons", "AtlasGrid", Qgis.Info)
        dj_areas = []
        merged.startEditing()
        for i, f in enumerate(merged.getFeatures()):
            f['dj_cellnum'] = i+1

            # Find northwest corner by looking for the minimum x at the maximum y of the polygon's boundary
            min_x = 9999999999
            max_y = -9999999999
            geom = f.geometry() #.asMultiPolygon()
            #QgsMessageLog.logMessage(f"Processing disjoint polygon {i+1} geometry {geom}", "AtlasGrid", Qgis.Info)
            #boundary = geom.boundary()
            for pt in geom.vertices():
                if pt.y() > max_y:
                    max_y = pt.y()
                    min_x = pt.x()
                elif pt.y() == max_y and pt.x() < min_x:
                    min_x = pt.x()
            dj_areas.append( (i+1, min_x, max_y) )
            QgsMessageLog.logMessage("Disjoint polygon {}: min_x = {}, max_y = {}".format(i+1,min_x,max_y), "AtlasGrid", Qgis.Info)
            merged.updateFeature(f)

        merged.commitChanges()

        # Sort the list by max_y (descending) and min_x (ascending)
        dj_areas.sort(key=lambda x: (-x[2], x[1])) 

        # Iterate the list, select grid cells within each disjoint polygon and assign the disjoint cell number according to the sorted order
        cell_idx = 0
        grid.startEditing()
        for area in dj_areas:
            str = "dj_cellnum = {}".format(area[0])
            request = QgsFeatureRequest(QgsExpression(str))
            for f in merged.getFeatures(request):
                geom = f.geometry()
                # Select grid cells within this geometry
                str2 = "within($geometry, geom_from_wkt('{}'))".format(geom.asWkt())
                request2 = QgsFeatureRequest(QgsExpression(str2))
                for gf in grid.getFeatures(request2):
                    cell_idx += 1
                    gf['dj_cellnum'] = cell_idx
                    grid.updateFeature(gf)

        grid.commitChanges()

        return

    def identifyCellsToDelete(self,grid,aoi):
        if self.feedback:
            self.feedback.pushInfo("Identifying mapsheets to be deleted")
            curr_prog = self.feedback.progress()
        # Generate line layer from grid polygons
        lines = processing.run("native:polygonstolines", {'INPUT':grid,'OUTPUT':'TEMPORARY_OUTPUT'}, feedback=self.feedback)['OUTPUT']

        # Split polygons by lines
        if self.feedback:
            prog_step = int((100-curr_prog)/5)
            self.feedback.setProgress(curr_prog + prog_step)
            self.feedback.pushInfo("Splitting grid")
        split = processing.run('native:splitwithlines', {'INPUT':grid,'LINES':lines, 'OUTPUT':'TEMPORARY_OUTPUT'}, feedback=self.feedback)['OUTPUT']

        # Add the split layer temporarily to the project (to be able to reference it in a field calculator expression)
        QgsProject.instance().addMapLayer(split, addToLegend=False)
        split.setName('split')
        splitToDelete = split

        # Use field calculator to determine which cells overlap each other
        if self.feedback:
            self.feedback.setProgress(curr_prog + (2*prog_step))
            self.feedback.pushInfo("Calculating overlap")

        alg_params = {
            'FIELD_LENGTH': 20,
            'FIELD_NAME': 'overlaps',
            'FIELD_PRECISION': 0,
            'FIELD_TYPE': 2,  # Text
            'FORMULA': "array_to_string(array_sort( aggregate( layer:= '{}', aggregate:='array_agg', expression:=cellname, filter:=contains($geometry, geometry(@parent)))))".format(split.name()),
            'INPUT': split,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }
        split = processing.run('native:fieldcalculator', alg_params, feedback=self.feedback)['OUTPUT']

        # Are grid and aoi in the same reference system?
        if grid.crs().authid() != aoi.crs().authid():
            projected = True
            proj_aoi = self.reprojectAOI(aoi,grid.crs().authid())
        else:
            proj_aoi = aoi.materialize(QgsFeatureRequest().setFilterFids(aoi.allFeatureIds()))
        QgsProject.instance().addMapLayer(proj_aoi, addToLegend=False)

        # Use field calculator to determine which cells to keep initially
        if self.feedback:
            self.feedback.setProgress(curr_prog + (3*prog_step))
            self.feedback.pushInfo("Calculating sheets to keep")
        alg_params = {
            'FIELD_LENGTH': 0,
            'FIELD_NAME': 'keep',
            'FIELD_PRECISION': 0,
            'FIELD_TYPE': 6,  # Boolean
            'FORMULA': "aggregate( layer:= '{}', aggregate:='count', expression:=@id, filter:=intersects($geometry, geometry(@parent))) > 0".format(proj_aoi.id()),
            'INPUT': split,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }
        split = processing.run('native:fieldcalculator', alg_params, feedback=self.feedback)['OUTPUT']

        # Check for intersection in the overlaps
        if self.feedback:
            self.feedback.setProgress(curr_prog + (4*prog_step))
            self.feedback.pushInfo("Checking for intersections in the overlaps")
        split.startEditing()
        for f in split.getFeatures():
            overlaps = f["overlaps"].split(',') if f["overlaps"] else []
            if f["keep"] and len(overlaps)>1:
                str = "cellname in ({}) and cellname = overlaps".format(','.join("'{}'".format(o) for o in overlaps))
                request = QgsFeatureRequest(QgsExpression(str))
                alreadyKept = False
                for o in split.getFeatures(request):
                    if o["keep"]:
                        alreadyKept = True
                
                if not alreadyKept:
                    o["keep"] = True
                    split.updateFeature(o)
                    
        split.commitChanges()

        str = "cellname = overlaps and not keep"
        request = QgsFeatureRequest(QgsExpression(str))
        toBeDeleted = []
        for f in split.getFeatures(request):
            toBeDeleted.append(f["cellname"])

        # Remove the temporary layer again
        QgsProject.instance().removeMapLayer(splitToDelete)
        QgsProject.instance().removeMapLayer(proj_aoi)

        return toBeDeleted

    def reprojectAOI(self,aoi,targetCrs):
        # Reproject layer
        alg_params = {
            'CONVERT_CURVED_GEOMETRIES': False,
            'INPUT': aoi,
            'OPERATION': '',
            'TARGET_CRS': QgsCoordinateReferenceSystem(targetCrs),
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }
        proj_aoi = processing.run('native:reprojectlayer', alg_params)['OUTPUT']
        QgsProject.instance().addMapLayer(proj_aoi, addToLegend=False)
        return proj_aoi

