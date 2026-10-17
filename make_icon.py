"""Writes icon.ico for build.bat (the .exe icon). The same drawing is used for the app's windows."""
import appicon

appicon.write_ico("icon.ico")
print("icon.ico written")
