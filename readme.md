# AtlasGrid v. 2.x

## Purpose

This plugin can be used to create a polygon layer consisting of evenly sized, rectangular polygons, suitable for use as a coverage layer in an atlas print layout.

## Background

Consider a map like the one shown below. You want to make an atlas plot, that divides the municipality polygon into rows and columns of mapsheets in a scale of 1:25.000. And furthermore you want the mapsheets to overlap each other by 10% horizontally and vertically.
![map](./images/map.png)

For this purpose, you need a polygon layer with rectangular polygons in a size that matches the map item on your print layout at the given map scale. To achieve this manually, you would have to calculate the real-world size of your rectangles, optionally taking into account that you want an overlap, and then create the number of rectangles necessary to cover the area - a quite tedious task! 

## With the plugin

Using the plugin, all these calculations and the creation of polygons will be achieved automatically.

As shown in the illustration below, when you activate the plugin, a dialog is shown where you pick the print layout and the map item that should display your mapsheets. Furthermore, you specify an overlap, if you want this. 

If you want to only create mapsheets where they cover a given area of interest (and not the whole extent), you choose the layer containing your AoI and check the Delete-checkbox.

You then choose the extent of your atlas or map book, either by inputting coordinates manually or (probably more often) by selecting an existing layer as the extent. And finally the output CRS for the layer being created.

<img src="./images/atlasgrid_dialog.png" title="" alt="map" data-align="center">

At the bottom of the dialog the plugin will show the map scale and cell size of your map item retrieved from your layout, and the resulting number of rows and columns of mapsheets when everything has been picked.

## The result

When the parameters have been set, and you press the OK button, the plugin will create a polygon layer consisting of the necessary rectangles in the appropriate size, number and optionally overlap. It will furthermore add an attribute to the layer containing a cell name, so that columns are named with letters (A-Z) and row are named with numbers. The most northwesterly placed rectangle will be 'A1', its neighbour to the east 'B1' and to the south 'A2'.

An example is  shown below:

![map](./images/atlasgrid.png)

Furthermore - if you prefer sequentially numbered mapsheets - an attribute with the mapsheet number will be calculated along side the cellname. Below you can see the cell names to the left and the cell numbers to the right.

Cells are numbered from west to east starting with the northernmost cells and continuing southward.

![map](./images/cellname_vs_cellnums.png)

# The processing plugin

All the funtionality mentioned above is also implemented as a processing plugin, meaning that you can incorporate the functionality in a QGIS model.

![map](./images/processing_plugin.png)

Find it in your Processing Toolbox under 'AtlasGrid'.
