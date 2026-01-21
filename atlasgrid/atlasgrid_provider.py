# -*- coding: utf-8 -*-

from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsProcessingProvider
from .atlasgrid_algorithm import AtlasGridProcessingAlgorithm

class AtlasGridProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        self.addAlgorithm(AtlasGridProcessingAlgorithm())

    def id(self):
        return "atlasgrid"

    def name(self):
        return "AtlasGrid"

    def icon(self):
        return QIcon(':/plugins/atlasgrid/atlasgrid.png')
