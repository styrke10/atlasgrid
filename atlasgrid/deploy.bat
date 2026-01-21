pyuic6 -x atlasgrid_dialog_base.ui -o resources.py
"C:\Qt\6.10.1\mingw_64\bin\rcc.exe" -g python -o resources.py resources.qrc
"C:\OSGeo4W\apps\Python312\Scripts\pb_tool.exe" deploy
