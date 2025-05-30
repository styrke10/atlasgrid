# -*- coding: utf-8 -*-
"""
/***************************************************************************
 AtlasGrid
                                 A QGIS plugin
 This plugin can be used for creating a regular coverage grid for atlas plots
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                             -------------------
        begin                : 2024-06-24
        copyright            : (C) 2024 by Styrke10 ApS
        email                : morten@styrke10.dk
        git sha              : $Format:%H$
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
 This script initializes the plugin, making it known to QGIS.
"""


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load AtlasGrid class from file AtlasGrid.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    #
    from .atlasgrid import AtlasGrid
    return AtlasGrid(iface)
