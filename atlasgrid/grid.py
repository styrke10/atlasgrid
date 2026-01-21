# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QVariant, QMetaType
from qgis.core import Qgis, QgsProject, QgsVectorLayer, QgsFeature, QgsFeatureRequest, QgsExpression, QgsMessageLog, \
                      QgsField, QgsRectangle, QgsGeometry, QgsVector, QgsLayoutMeasurement, QgsLayoutMeasurementConverter, \
                      QgsCoordinateReferenceSystem, QgsProcessingFeatureSourceDefinition
from qgis.core.additions.edit import edit
from qgis.utils import iface
from qgis import processing

class GridCreator():
    feedback = None
    crs = None
    
    def __init__(self):
        pass

    def setCRS(self,crs):
        self.crs = crs

    def setFeedback(self,feedback):
        self.feedback = feedback
        return

    def logMessage(self,message,level=Qgis.MessageLevel.Info):
        if self.feedback:
            self.feedback.pushInfo(message)
        else:
            QgsMessageLog.logMessage(message, "AtlasGrid", level)
        return
    
    def calcGridMetrics(self,mapScale,extent,atlasCellSize,horizOverlap,vertOverlap):
        self.logMessage("Calculating grid metrics")
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
        self.logMessage("Creating grid (v. 2.1.0)")
        
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
            self.calculateDisjointCellNums(gridLayer,aoiLayer,rwDim)
        
        return gridLayer

    def calculateDisjointCellNums(self,grid,aoi,rwDim):
        self.logMessage("Calculating disjoint cell numbers")
        # Dissolve AOI keeping disjoints AOIs separate
        alg_params = {'INPUT': aoi,
                      'FIELD':[],
                      'SEPARATE_DISJOINT':True,
                      'OUTPUT':'TEMPORARY_OUTPUT'
                      }
        merged_aois = processing.run("native:dissolve", alg_params)['OUTPUT']
        merged_aois.setName('merged_aois')

        # Add autoincremental field (unique ID)
        alg_params = {
            'INPUT': merged_aois,
            'FIELD_NAME': 'uid',
            'START': 1,
            'GROUP_FIELDS': [],
            'MODULUS': 0,
            'OUTPUT': 'memory:'
        }
        merged_unique_aois = processing.run('native:addautoincrementalfield', alg_params)['OUTPUT']
        merged_unique_aois.setName('merged_unique_aois')

        # Create copy of gridlayer, where all grid cells are shrunk to their net width/height 
        # to ensure disjoint polygons do not overlap or touch at edges
        shrink_x = (rwDim[0] - rwDim[2]) / 2
        shrink_y = (rwDim[1] - rwDim[3]) / 2
        copyLayer = QgsVectorLayer("Polygon?crs={}".format(self.crs), 'shrunk_cells', "memory")
        
        # Resolve the correct enum for Int across PyQt versions
        META_INT = getattr(QMetaType, 'Int', getattr(QMetaType.Type, 'Int'))

        fields = [
            QgsField('cellnum', META_INT),
            QgsField('dj_cellnum', META_INT),
        ]

        copyLayer.dataProvider().addAttributes(fields)
        copyLayer.updateFields()

        copyLayer.startEditing()

        for f in grid.getFeatures():
            geom = f.geometry().boundingBox()
            shrunkenCell = QgsRectangle(geom.xMinimum()+shrink_x, geom.yMinimum()+shrink_y, geom.xMaximum()-shrink_x, geom.yMaximum()-shrink_y)
            shrunkenFeat = QgsFeature(copyLayer.fields())
            shrunkenFeat.setGeometry(QgsGeometry.fromRect(shrunkenCell))
            shrunkenFeat["cellnum"] = f["cellnum"]
            copyLayer.dataProvider().addFeatures([shrunkenFeat])
        copyLayer.commitChanges()

        # Add layers to layer panel to be able to use them in selections below
        QgsProject.instance().addMapLayer(copyLayer, False)
        QgsProject.instance().addMapLayer(merged_unique_aois, False)

        # Select all cells in the copy layer without an assignment in 'dj_cellnum' until all are assigned
        cellnum = 0
        f_idx = copyLayer.fields().indexOf("dj_cellnum")
        copyLayer.selectByExpression('is_empty_or_null(dj_cellnum)', QgsVectorLayer.SetSelection)
        while copyLayer.selectedFeatureCount() > 0:
            # Select the first (northwestern most) cell 
            cell = next(copyLayer.getSelectedFeatures(QgsFeatureRequest().addOrderBy("cellnum", ascending=True)))
            copyLayer.selectByExpression(f'cellnum = {cell["cellnum"]}')

            # Select alternating aois and cells until the number of cells selected doesn't change
            cellsSelected = 1
            continueSelecting = True

            while continueSelecting:
                alg_params = {
                        'INPUT': merged_unique_aois,
                        'PREDICATE': [0],        # 0 = intersects
                        'INTERSECT': QgsProcessingFeatureSourceDefinition(copyLayer.id(),selectedFeaturesOnly = True),
                        'METHOD': 1             # add to selection
                }
                processing.run('native:selectbylocation', alg_params)

                alg_params = {
                        'INPUT': copyLayer,
                        'PREDICATE': [0],        # 0 = intersects
                        'INTERSECT': QgsProcessingFeatureSourceDefinition(merged_unique_aois.id(),selectedFeaturesOnly = True),
                        'METHOD': 1             # add to selection
                }
                processing.run('native:selectbylocation', alg_params)

                if cellsSelected < copyLayer.selectedFeatureCount():
                    cellsSelected = copyLayer.selectedFeatureCount()
                    continueSelecting = True
                else:
                    continueSelecting = False

            # All cells selected - start numbering
            copyLayer.startEditing()
            for cell in copyLayer.getSelectedFeatures(QgsFeatureRequest().addOrderBy("cellnum", ascending=True)):
                cellnum += 1
                cell.setAttribute(f_idx, cellnum)
                copyLayer.updateFeature(cell)
            copyLayer.commitChanges()

            copyLayer.selectByExpression('is_empty_or_null(dj_cellnum)', QgsVectorLayer.SetSelection)
            merged_unique_aois.removeSelection()

        # Copy the value of dj_cellnum from the copyLayer to the grid
        t_idx = grid.fields().indexOf("dj_cellnum")

        # Collect values to update
        lookup = {}
        for f in copyLayer.getFeatures():
            lookup[f["cellnum"]] = f["dj_cellnum"]

        # Prepare changes
        changes = {}
        for f in grid.getFeatures():
            key = f["cellnum"]
            changes[f.id()] = {t_idx: lookup[key]}

        # Apply changes in bulk
        with edit(grid):
            grid.dataProvider().changeAttributeValues(changes)

        # Remove temporary layers from layer panel
        QgsProject.instance().removeMapLayers([copyLayer, merged_unique_aois])

        return

    def identifyCellsToDelete(self,grid,aoi):
        self.logMessage("Identifying mapsheets to be deleted")
        if self.feedback:
            curr_prog = self.feedback.progress()
        # Generate line layer from grid polygons
        lines = processing.run("native:polygonstolines", {'INPUT':grid,'OUTPUT':'TEMPORARY_OUTPUT'}, feedback=self.feedback)['OUTPUT']

        # Split polygons by lines
        self.logMessage("Splitting grid")
        if self.feedback:
            prog_step = int((100-curr_prog)/5)
            self.feedback.setProgress(curr_prog + prog_step)
        split = processing.run('native:splitwithlines', {'INPUT':grid,'LINES':lines, 'OUTPUT':'TEMPORARY_OUTPUT'}, feedback=self.feedback)['OUTPUT']

        # Add the split layer temporarily to the project (to be able to reference it in a field calculator expression)
        QgsProject.instance().addMapLayer(split, addToLegend=False)
        split.setName('split')

        # Use field calculator to determine which cells overlap each other
        self.logMessage("Calculating overlap")
        if self.feedback:
            self.feedback.setProgress(curr_prog + (2*prog_step))

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
        self.logMessage("Locating sheets to keep")
        if self.feedback:
            self.feedback.setProgress(curr_prog + (3*prog_step))
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
        self.logMessage("Checking for intersections in the overlaps")
        if self.feedback:
            self.feedback.setProgress(curr_prog + (4*prog_step))
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
        QgsProject.instance().removeMapLayer(split)
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


