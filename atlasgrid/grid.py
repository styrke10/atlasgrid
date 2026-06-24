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

    def identifyCellsToDelete(self, grid, aoi):
        """Return the list of cellnames whose mapsheets do not need to be kept.

        A mapsheet is kept if any part of it intersects the AOI. Where two or
        more overlapping sheets share the AOI *only* in their mutual overlap
        region, a single representative sheet is retained instead of all of
        them.

        This implementation is deliberately independent of the runtime
        environment:
          * temporary layers are referenced inside expressions by *id*, never
            by name, so a layer the user happens to have called "split" can no
            longer be picked up by the aggregate() calls;
          * the AOI/grid CRS comparison uses the CRS objects (an empty authid
            on a custom CRS no longer defeats the reprojection);
          * cell membership of each split piece is decided with an interior
            point rather than polygon-in-polygon containment, which removes the
            dependency on the exact GEOS version / coordinate precision;
          * every keep/delete decision is made in plain Python on values read
            once, so there is no editing-while-iterating and no reliance on
            provider-specific feature ordering;
          * temporary layers are removed in a finally block, so a failure
            partway through can no longer leak layers into the project (which
            previously caused name clashes on the next run).
        """
        self.logMessage("Identifying mapsheets to be deleted")
        debug = False
        project = QgsProject.instance()

        curr_prog = self.feedback.progress() if self.feedback else 0
        prog_step = int((100 - curr_prog) / 5) if self.feedback else 0

        # Layers pushed into the project so they can be resolved by id inside
        # expression aggregates. Tracked here for guaranteed cleanup.
        temp_project_layers = []

        def _is_null(v):
            return v is None or (isinstance(v, QVariant) and v.isNull())

        def _as_bool(v):
            # Booleans round-trip as real bools on memory layers but can come
            # back as 0/1 (or NULL) on OGR/GeoPackage temporary outputs, so
            # normalise defensively.
            if _is_null(v):
                return False
            return str(v).strip().lower() in ('1', 'true', 't')

        def _as_list(v):
            if _is_null(v):
                return []
            s = str(v).strip()
            if s == '' or s.upper() == 'NULL':
                return []
            return [p for p in s.split(',') if p != '']

        try:
            # 1. Grid boundaries as a line layer.
            lines = processing.run(
                "native:polygonstolines",
                {'INPUT': grid, 
                 'OUTPUT': 'TEMPORARY_OUTPUT'},
                feedback=self.feedback)['OUTPUT']

            # 2. Split every cell along all boundary lines, so overlap regions become their own pieces.
            self.logMessage("Splitting grid")
            if self.feedback:
                self.feedback.setProgress(curr_prog + prog_step)
            split_base = processing.run(
                'native:splitwithlines',
                {'INPUT': grid, 
                 'LINES': lines, 
                 'OUTPUT': 'TEMPORARY_OUTPUT'},
                feedback=self.feedback)['OUTPUT']
            split_base.setName('atlasgrid_split')

            # Must be in the project to be resolvable by id inside aggregate().
            project.addMapLayer(split_base, addToLegend=debug)
            temp_project_layers.append(split_base)

            # 3. For each piece, build the sorted list of cells that cover it.
            #    Testing containment of an interior point (point_on_surface)
            #    rather than the whole polygon avoids GEOS edge-precision
            #    differences between installations.
            self.logMessage("Calculating overlap")
            if self.feedback:
                self.feedback.setProgress(curr_prog + (2 * prog_step))
            overlaps_formula = (
                "array_to_string(array_sort(aggregate("
                "layer:='{lid}',"
                "aggregate:='array_agg',"
                "expression:=\"cellname\","
                "filter:=contains($geometry, point_on_surface(geometry(@parent)))"
                ")))"
            ).format(lid=split_base.id())
            alg_params = {
                'FIELD_LENGTH': 20,
                'FIELD_NAME': 'overlaps',
                'FIELD_PRECISION': 0,
                'FIELD_TYPE': 2,  # Text
                'FORMULA': overlaps_formula,
                'INPUT': split_base,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }
            split = processing.run('native:fieldcalculator', alg_params, feedback=self.feedback)['OUTPUT']

            # 4. Make sure the AOI is in the grid CRS. Compare the CRS objects
            #    rather than authids (which may be empty for custom CRSs).
            if grid.crs() != aoi.crs():
                self.logMessage("Reprojecting AOI to grid CRS")
                proj_aoi = processing.run(
                    'native:reprojectlayer',
                    {'INPUT': aoi,
                     'TARGET_CRS': grid.crs(),
                     'CONVERT_CURVED_GEOMETRIES': False,
                     'OPERATION': '',
                     'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']
            else:
                proj_aoi = aoi.materialize(QgsFeatureRequest().setFilterFids(aoi.allFeatureIds()))
            proj_aoi.setName('atlasgrid_aoi')
            project.addMapLayer(proj_aoi, addToLegend=debug)
            temp_project_layers.append(proj_aoi)

            # 5. Flag pieces that intersect the AOI (AOI referenced by id).
            self.logMessage("Locating sheets to keep")
            if self.feedback:
                self.feedback.setProgress(curr_prog + (3 * prog_step))
            keep_formula = (
                "aggregate("
                "layer:='{lid}',"
                "aggregate:='count',"
                "expression:=$id,"
                "filter:=intersects($geometry, geometry(@parent))"
                ") > 0"
            ).format(lid=proj_aoi.id())
            alg_params = {
                'FIELD_LENGTH': 0,
                'FIELD_NAME': 'keep',
                'FIELD_PRECISION': 0,
                'FIELD_TYPE': 6,  # Boolean
                'FORMULA': keep_formula,
                'INPUT': split,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }
            split = processing.run('native:fieldcalculator', alg_params, feedback=self.feedback)['OUTPUT']

            # 6. Read everything into plain Python. From here the decision logic
            #    is fully deterministic and provider-independent.
            self.logMessage("Checking for intersections in the overlaps")
            if self.feedback:
                self.feedback.setProgress(curr_prog + (4 * prog_step))

            pieces = []            # list of (cellname, overlaps_list, keep_bool)
            cells_with_core = set()
            kept_core = {}         # cellname -> bool (does the cell survive?)

            for f in split.getFeatures():
                cellname = f['cellname']
                if _is_null(cellname):
                    continue
                cellname = str(cellname)
                overlaps = _as_list(f['overlaps'])
                keep = _as_bool(f['keep'])
                pieces.append((cellname, overlaps, keep))

                # A "core" piece is one covered only by its own cell.
                if overlaps == [cellname]:
                    cells_with_core.add(cellname)
                    if keep:
                        kept_core[cellname] = True
                    else:
                        kept_core.setdefault(cellname, False)

            # 7. For every AOI-intersecting overlap region, make sure at least
            #    one covering sheet is retained. Regions are processed in a
            #    stable sorted order and the alphabetically first cell is chosen
            #    as the representative.
            overlap_regions = sorted(
                {tuple(ov) for (cn, ov, kp) in pieces if kp and len(ov) > 1}
            )
            for region in overlap_regions:
                if any(kept_core.get(c, False) for c in region):
                    continue
                candidates = [c for c in region if c in cells_with_core] or list(region)
                representative = sorted(candidates)[0]
                kept_core[representative] = True

            # 8. Any cell that has a core piece but is still not kept is deleted.
            toBeDeleted = sorted(
                cell for cell in cells_with_core if not kept_core.get(cell, False)
            )

            self.logMessage("Cells to be deleted: {}".format(toBeDeleted))
            return toBeDeleted

        finally:
            # Guaranteed cleanup, even if a processing step raised.
            if not debug and temp_project_layers:
                project.removeMapLayers([lyr.id() for lyr in temp_project_layers])

