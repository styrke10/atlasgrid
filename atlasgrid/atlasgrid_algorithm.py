# -*- coding: utf-8 -*-

from PyQt5.QtGui import QIcon
from qgis.core import (
    QgsMessageLog, 
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterLayout,
    QgsProcessingParameterLayoutItem,
    QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterExtent,
    QgsProcessingParameterCrs,
    QgsProcessingParameterFeatureSink,
    QgsFeatureSink,
    QgsLayoutItemRegistry
)
from qgis.utils import iface
from .grid import GridCreator

class AtlasGridProcessingAlgorithm(QgsProcessingAlgorithm):

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    LAYOUT = 'LAYOUT'
    MAPITEM = 'MAPITEM'
    HORZOVERLAP = 'HORZOVERLAP'
    VERTOVERLAP = 'VERTOVERLAP'
    DELETENONINTERSECTS = 'DELETENONINTERSECTS'
    AOI = 'AOI'
    EXTENT = 'EXTENT'
    CRS = 'CRS'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterLayout(self.LAYOUT, 'Print layout')
        )
        self.addParameter(
            QgsProcessingParameterLayoutItem(self.MAPITEM, 'Map Item',
                itemType=QgsLayoutItemRegistry.LayoutMap,
                parentLayoutParameterName = self.LAYOUT)
        )
        self.addParameter(
            QgsProcessingParameterNumber(self.HORZOVERLAP, 'Horizontal overlap (in %)',
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=0,
                optional=False,
                minValue=0,
                maxValue=50)
        )
        self.addParameter(
            QgsProcessingParameterNumber(self.VERTOVERLAP, 'Vertical overlap (in %)',
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=0,
                optional=False,
                minValue=0,
                maxValue=50)
        )
        self.addParameter(
            QgsProcessingParameterBoolean(self.DELETENONINTERSECTS, 'Delete sheets not intersecting with AoI',False)
        )
        self.addParameter(
            QgsProcessingParameterVectorLayer(self.AOI, 'Layer with area of interest (AoI)')
        )
        self.addParameter(
            QgsProcessingParameterExtent(self.EXTENT, 'Specify extent of grid')
        )
        self.addParameter(
            QgsProcessingParameterCrs(self.CRS, 'Output CRS'
                ,defaultValue=iface.mapCanvas().mapSettings().destinationCrs()
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(self.OUTPUT,'AtlasGrid')
        )

    def processAlgorithm(self, parameters, context, feedback):
        layout = self.parameterAsLayout(parameters, self.LAYOUT, context)
        mapitem = self.parameterAsLayoutItem(parameters, self.MAPITEM, context, layout)
        horzOverlap = self.parameterAsInt(parameters, self.HORZOVERLAP, context)
        vertOverlap = self.parameterAsInt(parameters, self.VERTOVERLAP, context)
        deleteNonIntersects = self.parameterAsBoolean(parameters, self.DELETENONINTERSECTS, context)
        aoiLayer = self.parameterAsVectorLayer(parameters, self.AOI, context)
        extent = self.parameterAsExtent(parameters, self.EXTENT, context)
        crs = self.parameterAsCrs(parameters, self.CRS, context)

        gridCreator = GridCreator()
        # Set default CRS and extent and initialize the GridCreator object
        gridCreator.setCRS(crs.authid())
        gridCreator.setFeedback(feedback)
        mapScale = mapitem.scale()
        atlasCellSize = mapitem.sizeWithUnits()

        (rwDimensions,nRowsAndCols,gridExtent) = gridCreator.calcGridMetrics(mapScale,extent,atlasCellSize,horzOverlap,vertOverlap)
        
        gridLayer = gridCreator.createGrid(
                        mapScale,gridExtent,rwDimensions,nRowsAndCols,deleteNonIntersects,aoiLayer)

        (sink, dest_id) = self.parameterAsSink(parameters,
                        self.OUTPUT,context,gridLayer.fields(),gridLayer.wkbType(),gridLayer.sourceCrs())
        
        for current, feature in enumerate(gridLayer.getFeatures()):
            # Add a feature to the sink
            sink.addFeature(feature, QgsFeatureSink.Flag.FastInsert)

        return {self.OUTPUT: dest_id}
    
    def name(self):
        return "Create AtlasGrid"

    def displayName(self):
        return "AtlasGrid"

    def group(self):
        return "AtlasGrid"

    def groupId(self):
        return "atlasgrid"

    def createInstance(self):
        return AtlasGridProcessingAlgorithm()

    def icon(self):
        return QIcon(':/plugins/atlasgrid/atlasgrid.png')

    def shortDescription(self):
        str = """<p>This plugin can be used to create a polygon layer consisting of evenly sized, rectangular polygons, suitable for use as a coverage layer in an atlas print layout.</p>
        
        <p>The plugin comes with a graphical user interface activated through the menu or by a button on the toolbar as well as a processing algorithm. The two parts provide the same functionality.</p>
        
        <p>The processing algorithm takes the following parameters:</p>
        <ul>
        <li><b>Print layout:</b> Name of the print layout that should contain the atlas.</li>
        <li><b>Map item:</b> Name of the map item on the layout that should contain the mapsheets.</li>
        <li><b>Horizontal overlap:</b> The horizontal overlap in percentage of the map item width.</li>
        <li><b>Vertical overlap:</b> The vertical overlap in percentage of the map item height.</li>
        <li><b>Delete sheets not intersecting with the area of interest:</b> Determines whether mapsheets not containing any parts of the objects in the area of interest are deleted.</li>
        <li><b>Layer with area of interest:</b> The layer that defines the area of interest.</li>
        <li><b>Extent of grid:</b> Specification of the rectangular extent, that the grid should cover.</li>
        <li><b>Output CRS:</b> The coordinate reference system in which the grid should be created.</li>
        <li><b>AtlasGrid</b> Specification of the output destination layer.</li>
        </ul>
        
        <p>Developed by <a href="https://www.styrke10.dk">Styrke 10 ApS</a>.</p>



        """
        return str
