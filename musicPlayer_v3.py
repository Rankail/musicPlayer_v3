import sys
from os import listdir
from os.path import splitext, basename, dirname, isfile, isdir
import random
from bisect import bisect_left
import time
from math import ceil
from typing import Iterable
from PyQt5.QtWidgets import *
from PyQt5.QtGui import *
from PyQt5.QtCore import QModelIndex, QSortFilterProxyModel, Qt, pyqtSignal, QObject, QThread, QSize, QTimer
import vlc
import eyed3
import ctypes

#----------------------------------
#----- Application User Model -----
#----------------------------------
#changes AppUserModel to create new AppGroup with custom icon
myappid = 'RTS.RTSMusic.musicPlayer.3.0' # arbitrary string
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

#----------------------------------
#------------- Init Qt ------------
#----------------------------------
app = QApplication(sys.argv)

#-------------------------------------------------------------------
#--------------------- Define / Init Variables ---------------------
#-------------------------------------------------------------------

#states
playing = True
paused = False

filterChange = False
selectionAboutChanged = False

#paths
iniDir = "D:/IT/Python/qt/musicPlayer"
rscDir = iniDir+"/_rsc"

#theme
bg1 = "#333"
bg2 = "#222"
textCol = "#ddd"
selectCol = "#090"

#all paths
paths = []
folders = []
removedPaths = []
#list of all song-objects
allSongs = {}

playlists = {}
#list of currently shown songnames
songList = []

artistList = ["-- None Selected --"]
albumList = ["-- None Selected --"]

#cur song
curIndex = 0
curSongname = ""

#filters
filters = {
	"search": "",
	"album": "",
	"artist": "",
	"playlist": ""
}

#time
curTimePos = 0

#song length in sec
curSongLen = 0

#volume
curVolume = 50

#media-player
vlcInstance = vlc.Instance()
vlcInstance.log_unset()
vlcPlayer = vlcInstance.media_player_new()

#----------------------------------
#-------- Other Functions ---------
#----------------------------------

#get filename from path
def getPureName(filename: str) -> str:
	return splitext(basename(filename))[0]

#checks if string contains all of the words
def hasSearchWords(string: str) -> bool:
	string = string.lower()
	for word in filters["search"].split():
		if not word.lower() in string:
			return False
	
	return True

def findRowBySongname(songname: str) -> int:
	findsTitleStart = songTableModel.findItems(songname.split(" - ")[0], Qt.MatchFlag.MatchStartsWith, 0)
	findsArtistEnd = songTableModel.findItems(songname.split(" - ")[-1], Qt.MatchFlag.MatchEndsWith, 1)
	indicesTitle = [songTableModel.indexFromItem(f).row() for f in findsTitleStart]
	for f in findsArtistEnd:
		i = songTableModel.indexFromItem(f).row()
		if i in indicesTitle:
			return filterSongTable.mapFromSource(songTableModel.index(i, 0)).row()
	
	return -1

#----------------------------------
#-------- Update Functions --------
#----------------------------------

def updatePlayTime():
	global curTimePos
	if not playing or paused: return

	curTimePos = max(0, int(vlcPlayer.get_time() / 1000))
	playTimeLbl.setText(time.strftime('%H:%M:%S', time.gmtime(curTimePos)))
	timeSlider.setValue(curTimePos)
	
	if vlcPlayer.get_state() == vlc.State.Ended:
		nextSong()
		return

	QTimer.singleShot(0, updatePlayTime)

#----------------------------------
#------ Add / Remove Song(s) ------
#----------------------------------

#thread-function
def songObjGenerator(paths: Iterable):
	paths = [p for p in paths if p.endswith(".mp3")]
	for path in paths:
		tag = eyed3.load(path)
		if tag is None:
			continue
		tag = tag.tag
		if tag is None:
			yield (getPureName(path), {"path": path, "title": getPureName(path), "artist": "unkown", "trackNumber": ""})
			continue
		obj = {"path": path, "title": "unknown title", "artist": "unknown", "album": "", "trackNumber": ""}
		if tag.title:
			obj["title"] = tag.title
		if tag.artist:
			obj["artist"] = tag.artist
		if tag.album:
			obj["album"] = tag.album
		if tag.track_num[0]:
			if tag.track_num[0] < 10:
				obj["trackNumber"] = "0"+str(tag.track_num[0])
			else:
				obj["trackNumber"] = str(tag.track_num[0])

		name = (obj["title"]+" - "+(obj["artist"]))

		yield (name, obj)
	

#thread-class
class SongLoader(QObject):
	loadedSong = pyqtSignal(str, object)
	finishedLoading = pyqtSignal()

	def addSongs(self, paths: Iterable):
		songObjGen = songObjGenerator(paths)
		for n, o in songObjGen:
			self.loadedSong.emit(n, o)

		self.finishedLoading.emit()

#communicate with thread
class EmitAddSong(QObject):
	addSongsSignal = pyqtSignal(list)

	def addSongs(self, paths: Iterable):
		self.addSongsSignal.emit(paths)
		
#add object created by thread to list
def addSongToList(name: str, obj: dict):
	global curIndex, allSongs, selectionAboutChanged
	if name in allSongs:
		if allSongs[name]["path"] in paths:
			paths.remove(allSongs[name]["path"])
		else:
			removedPaths.append(allSongs[name]["path"])

		allSongs[name] = obj

	else:
		if "artist" in obj and not obj["artist"] in artistList:
			i = bisect_left(artistList, obj["artist"])
			artistList.insert(i, obj["artist"])
			artistListBox.insertItem(i, obj["artist"])

		if "album" in obj and obj["album"] and not obj["album"] in albumList:
			i = bisect_left(albumList, obj["album"])
			albumList.insert(i, obj["album"])
			albumListBox.insertItem(i, obj["album"])

		allSongs[name] = obj

		songTableModel.insertRow(0, [
			QStandardItem(obj["title"]),
			QStandardItem(obj["artist"]),
			QStandardItem(obj["album"]),
			QStandardItem(obj["trackNumber"])
		])

		if name == curSongname:
			play(curSongname, startPos=curTimePos)

def finishedLoadingSongs():
	global selectionAboutChanged
	if curSongname in allSongs:
		i = findRowBySongname(curSongname)
		if i != -1:
			selectionAboutChanged = True
			songListBox.selectRow(i)
			songListBox.scrollTo(filterSongTable.index(i, 0), 3)
		else:
			songListBox.scrollTo(filterSongTable.index(0, 0))

#initialize thread+connections
loaderThread = QThread()
songLoader = SongLoader()
songLoader.moveToThread(loaderThread)
songLoader.loadedSong.connect(addSongToList)
songLoader.finishedLoading.connect(finishedLoadingSongs)
emitAddSong = EmitAddSong()
emitAddSong.addSongsSignal.connect(songLoader.addSongs)
loaderThread.start()

#adding single song
def addSong():
	path = QFileDialog.getOpenFileName(window, "Choose a song", None, "mp3 files (*.mp3)")[0]
	if path:
		if not (path in paths or dirname(path) in folders):
			if path in removedPaths:
				removedPaths.remove(path)
			else:
				paths.append(path)
		emitAddSong.addSongs([path])

#adding multiple songs
def addSongs():
	ps = QFileDialog.getOpenFileNames(window, "Choose songs", None, "mp3 files (*.mp3)")[0]
	if ps:
		ps = [p for p in paths if not (p in paths or dirname(p) in folders)]
		for p in ps:
			if p in removedPaths:
				removedPaths.remove(p)
			else:
				paths.append(p)
		emitAddSong.addSongs(paths)

#adding songs from folder
def addFolder():
	folderpath = QFileDialog.getExistingDirectory(window, "Choose a folder", None)
	if folderpath:
		if folderpath in folders:
			return
		folders.append(folderpath)
		ps = listdir(folderpath)
		ps = [folderpath+"/"+f for f in ps if f.endswith('.mp3')]
		ps = [p for p in ps if not p in paths]
		emitAddSong.addSongs(ps)

#----------------------------------
#-------- Playlist-Controls -------
#----------------------------------

def createPlaylist():
	dialog = QInputDialog(window)
	dialog.setInputMode(QInputDialog.InputMode.TextInput)
	dialog.setWindowTitle("Create Playlist")
	dialog.setFixedSize(QSize(250, 100))
	dialog.setLabelText("Playlist name:")
	dialog.setStyleSheet("* {background-color:"+bg1+";color:"+textCol+";font-size: 10pt; }")
	ok = dialog.exec()
	text = dialog.textValue()
	if ok and text:
		playlists[text] = []
		playListListBox.addItem(text)

def addToPlaylist(playlist: str, songname: str):
	playlists[playlist].append(songname)

def addShownSongsToPlaylist():
	dialog = QInputDialog(window)
	dialog.setComboBoxEditable(False)
	items = list(playlists.keys())
	items.insert(0, "-- None Selected --")
	dialog.setComboBoxItems(items)
	dialog.setWindowTitle("Add Shown Songs To Playlist")
	dialog.setFixedSize(QSize(350, 100))
	dialog.setLabelText("Select Playlist:")
	dialog.setStyleSheet("* {background-color:"+bg1+";color:"+textCol+";font-size: 10pt; }")
	ok = dialog.exec()
	playlist = dialog.textValue()
	if not (ok and playlist and playlist != "-- None Selected --"): return

	for i in range(filterSongTable.rowCount()):
		index0 = filterSongTable.index(i, 0)
		index1 = filterSongTable.index(i, 1)
		songname = (filterSongTable.data(index0))+" - "+(filterSongTable.data(index1))
		if not songname in playlists[playlist]:
			playlists[playlist].append(songname)

def renamePlaylist():
	dialog1 = QInputDialog(window)
	dialog1.setComboBoxEditable(False)
	items = list(playlists.keys())
	items.insert(0, "-- None Selected --")
	dialog1.setComboBoxItems(items)
	dialog1.setWindowTitle("Select Playlist To Rename")
	dialog1.setFixedSize(QSize(350, 100))
	dialog1.setLabelText("Select Playlist:")
	dialog1.setStyleSheet("* {background-color:"+bg1+";color:"+textCol+";font-size: 10pt; }")
	ok = dialog1.exec()
	playlist = dialog1.textValue()
	if not (ok and playlist and playlist != "-- None Selected --"): return

	dialog1 = QInputDialog(window)
	dialog1.setInputMode(QInputDialog.InputMode.TextInput)
	dialog1.setWindowTitle("New Playlist Name")
	dialog1.setFixedSize(QSize(350, 100))
	dialog1.setLabelText("Enter New Name for '"+playlist+"':")
	dialog1.setStyleSheet("* {background-color:"+bg1+";color:"+textCol+";font-size: 10pt; }")
	ok = dialog1.exec()
	newName = dialog1.textValue()
	if not (ok and newName): return

	playlists[newName] = playlists.pop(playlist)
	index = playListListBox.findText(playlist)
	if filters["playlist"] == playlist:
		playListListBox.setCurrentText(newName)
		filters["playlist"] = newName
	playListListBox.setItemText(index, newName)

def removeFromPlaylist(playlist: str, songname: str):
	global filterChange
	playlists[playlist].remove(songname)
	filterChange = True
	filterSongTable.setFilterFixedString("")

def delCurPlaylist():
	if filters["playlist"] and filters["playlist"] in playlists:
		dialog = QMessageBox()
		dialog.setWindowTitle("Delete Playlist?")
		dialog.setText("Do you want to delete the playlist '"+filters["playlist"]+"'?")
		dialog.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
		dialog.setDefaultButton(QMessageBox.StandardButton.Ok)
		dialog.setStyleSheet("* {background-color:"+bg1+";color:"+textCol+";font-size: 10pt; }")
		result = dialog.exec()
		if result == QMessageBox.StandardButton.Ok:
			playlists.pop(filters["playlist"])
			index = playListListBox.currentIndex()
			playListListBox.setCurrentText("-- None Selected --")
			playListListBox.removeItem(index)

#----------------------------------
#--------- Music-Controls ---------
#----------------------------------

def play(name: str, startPos=0):
	global curSongLen, curTimePos, playing, curSongname

	path = allSongs[name]["path"]
	if not path: return


	if playing:
		vlcPlayer.stop()

	media = vlcInstance.media_new(path)
	vlcPlayer.set_media(media)
	vlcPlayer.play()
	curTimePos = startPos
	timeSlider.setValue(startPos)

	curSongname = name
	curSongLbl.setText(name)
	
	playTimeLbl.setText(time.strftime('%H:%M:%S', time.gmtime(startPos)))

	if paused:
		playPauseBtn.setIcon(playBtnImg)
	else:
		playPauseBtn.setIcon(pauseBtnImg)

	#can't access some properties before the song is playing
	curState = vlcPlayer.get_state()
	while not(curState == vlc.State.Playing or curState == vlc.State.Paused):
		curState = vlcPlayer.get_state()
		time.sleep(0.001)

	#even though it says it's ready it still needs some time before you can set the volume ¯\_(ツ)_/¯
	time.sleep(0.01)
	playing = True
	if startPos != 0:
		vlcPlayer.set_time(startPos*1000)

	vlcPlayer.set_pause(paused)
	vlcPlayer.audio_set_volume(curVolume)

	curSongLen = vlcPlayer.get_length() / 1000
	songLenLbl.setText(time.strftime('%H:%M:%S', time.gmtime(int(curSongLen))))
	timeSlider.setMaximum(int(curSongLen))
	if not paused:
		updatePlayTime()

#start song at current index and set selection to index
def startSongByCurIndex():
	global curSongname
	index0 = filterSongTable.index(curIndex, 0)
	index1 = filterSongTable.index(curIndex, 1)
	curSongname = (filterSongTable.data(index0))+" - "+(filterSongTable.data(index1))
	songListBox.selectRow(curIndex)
	songListBox.scrollTo(index0)
	play(curSongname)

#play previous song
def prevSong():
	global curIndex
	if curIndex == -1: return
	allSelections = songListBox.selectionModel().selectedRows()
	if len(allSelections) <= 0: return
	curIndex = allSelections[0].row()
	if type(curIndex) == int and curIndex >= 0 and filterSongTable.rowCount() > 1 and playing:
		curIndex = (curIndex-1)%filterSongTable.rowCount()
		startSongByCurIndex()

#play next song
def nextSong():
	global curIndex
	if curIndex < 0: return
	allSelections = songListBox.selectionModel().selectedRows()
	if len(allSelections) <= 0: return
	curIndex = allSelections[0].row()
	if type(curIndex) == int and curIndex >= 0 and filterSongTable.rowCount() > 0 and playing:
		curIndex = (curIndex+1)%filterSongTable.rowCount()
		startSongByCurIndex()

def playPauseSong():
	global playing, paused
	if playing:
		paused = not paused
		vlcPlayer.set_pause(paused)
		if paused:
			playPauseBtn.setIcon(playBtnImg)
		else:
			playPauseBtn.setIcon(pauseBtnImg)
			QTimer.singleShot(0, updatePlayTime)

#----------------------------------
#------------- Events -------------
#----------------------------------
def songSelectedEvent(nIndex: QModelIndex, pIndex: QModelIndex):
	global curIndex, curSongname, selectionAboutChanged, playing
	if selectionAboutChanged:
		selectionAboutChanged = False
		return
	if filterChange:
		curIndex = -1
		curSongname = ""
		vlcPlayer.stop()
		curSongLbl.setText("")
		timeSlider.setValue(0)
		playTimeLbl.setText("00:00:00")
		songLenLbl.setText("00:00:00")
		playing = False
		return
	curIndex = nIndex.row()
	index0 = filterSongTable.index(curIndex, 0)
	index1 = filterSongTable.index(curIndex, 1)
	curSongname = (filterSongTable.data(index0))+" - "+(filterSongTable.data(index1))
	play(curSongname)

def volumeEvent(newVolume: int):
    global curVolume
    newVolume = max(0, min(int(newVolume), 100))
    if curVolume != newVolume:
        curVolume = newVolume
        volumeSlider.setValue(curVolume)
        vlcPlayer.audio_set_volume(curVolume)
        volumeIcon.setPixmap(volIconList[ceil(curVolume/25)])

def timeSlideEvent(pos: int):
    global curTimePos
    pos = int(float(pos))
    if curTimePos != pos:
        curTimePos = pos
        vlcPlayer.set_time(curTimePos*1000)
        playTimeLbl.setText(time.strftime('%H:%M:%S', time.gmtime(curTimePos)))

def clearFilters():
	global filterChange
	filterChange = True
	filters["search"] = ""
	filters["artist"] = ""
	filters["album"] = ""
	filters["playlist"] = ""
	filterSongTable.setFilterFixedString("")
	searchField.setText("")
	artistListBox.setCurrentText("-- None Selected --")
	albumListBox.setCurrentText("-- None Selected --")
	playListListBox.setCurrentText("-- None Selected --")

def searchEvent(text: str):
	global filterChange
	filterChange = True
	filters["search"] = text
	filterSongTable.setFilterFixedString("")
	albumListBox.setCurrentText("-- None Selected --")
	playListListBox.setCurrentText("-- None Selected --")

def artistFilterEvent(artist: str):
	global filterChange
	if not filterChange:
		filterChange = True
		if artist == "-- None Selected --":
			filters["artist"] = ""
		else:
			filters["artist"] = artist
		filters["album"] = ""
		filters["playlist"] = ""
		filterSongTable.setFilterFixedString("")
		albumListBox.setCurrentText("-- None Selected --")
		playListListBox.setCurrentText("-- None Selected --")

def albumFilterEvent(album: str):
	global filterChange
	if not filterChange:
		filterChange = True
		filters["artist"] = ""
		if album == "-- None Selected --":
			filters["album"] = ""
		else:
			filters["album"] = album
		filters["playlist"] = ""
		filterSongTable.setFilterFixedString("")
		artistListBox.setCurrentText("-- None Selected --")
		playListListBox.setCurrentText("-- None Selected --")

def playlistFilterEvent(playlist: str):
	global filterChange
	print("ou", playlist)
	if not filterChange:
		print("in", playlist)
		filterChange = True
		filters["artist"] = ""
		filters["album"] = ""
		if playlist == "-- None Selected --":
			filters["playlist"] = ""
		else:
			filters["playlist"] = playlist
		filterSongTable.setFilterFixedString("")
		artistListBox.setCurrentText("-- None Selected --")
		albumListBox.setCurrentText("-- None Selected --")

def sortChangedScroll(index, order):
	global curIndex
	allSelections = songListBox.selectionModel().selectedRows()
	if len(allSelections) <= 0:
		songListBox.scrollTo(filterSongTable.index(0, 0))
		return
	curIndex = allSelections[0].row()
	if filterSongTable.rowCount() > 0:
		songListBox.scrollTo(filterSongTable.index(curIndex, 0), 3)

def tableViewFilterEnded():
	global filterChange
	if filterChange:
		filterChange = False
		if filters["album"]:
			filterSongTable.sort(3, Qt.SortOrder.AscendingOrder)
			songListBox.showColumn(3)
		else:
			filterSongTable.sort(0, Qt.SortOrder.AscendingOrder)
			songListBox.hideColumn(3)

		allSelections = songListBox.selectionModel().selectedRows()
		if len(allSelections) <= 0:
			songListBox.scrollTo(filterSongTable.index(0, 0))
		else:
			songListBox.scrollTo(filterSongTable.index(allSelections[0].row(), 0), 3)

def shuffleSongs():
	global curIndex
	ies = list(range(filterSongTable.rowCount()))
	random.shuffle(ies)
	for i in range(filterSongTable.rowCount()):
		filterSongTable.setData(filterSongTable.index(i, 4), ies[i])

	filterSongTable.sort(4, Qt.SortOrder.AscendingOrder)
	allSelections = songListBox.selectionModel().selectedRows()
	if len(allSelections) > 0:
		curIndex = allSelections[0].row()
	if curIndex >= 0:
		songListBox.scrollTo(filterSongTable.index(curIndex, 0), 3)
	else:
		songListBox.scrollTo(filterSongTable.index(0, 0))

#-------------------------------------------------------------------
#------------------- Define / Init Window Parts --------------------
#-------------------------------------------------------------------

#----------------------------------
#------------- Window -------------
#----------------------------------
window = QMainWindow()
window.setWindowIcon(QIcon(rscDir+"/icon.png"))
window.setWindowTitle("Music Player")
window.resize(800, 800)

mainWidget = QWidget()
mainWidget.setStyleSheet("background-color:"+bg1+";color:"+textCol)
window.setCentralWidget(mainWidget)

#----------------------------------
#------------ Toolbar -------------
#----------------------------------
menubar = QMenuBar(mainWidget)
window.setMenuBar(menubar)

fileMenu = QMenu("File", menubar)
menubar.addMenu(fileMenu)
# menubar.addAction("Settings", openSettings)

addSongAction = QAction("Add Song", window)
addSongsAction = QAction("Add Songs", window)
addFolderAction = QAction("Add Folder", window)

addSongAction.setShortcut("Ctrl+O")
addSongsAction.setShortcut("Alt+O")
addFolderAction.setShortcut("Ctrl+Shift+O")

addSongAction.triggered.connect(addSong)
addSongsAction.triggered.connect(addSongs)
addFolderAction.triggered.connect(addFolder)

# delActiveSongAction = QAction("Remove Current Song", window)
# delShownSongsAction = QAction("Remove Shown Songs", window)
# delAllSongsAction = QAction("Remove All Songs", window)

# delActiveSongAction.triggered.connect(removeActiveSong)
# delShownSongsAction.triggered.connect(removeShownSongs)
# delAllSongsAction.triggered.connect(removeAllSongs)

fileMenu.addAction(addSongAction)
fileMenu.addAction(addSongsAction)
fileMenu.addAction(addFolderAction)
fileMenu.addSeparator()
# fileMenu.addAction(delActiveSongAction)
# fileMenu.addAction(delShownSongsAction)
# fileMenu.addAction(delAllSongsAction)

playListMenu = QMenu("Playlist", menubar)
menubar.addMenu(playListMenu)

newPlaylistAction = QAction("New Playlist", playListMenu)
renamePlaylistAction = QAction("Rename Playlist", playListMenu)
addShownToPlaylistAction = QAction("Add Shown Songs to Playlist", playListMenu)

newPlaylistAction.setShortcut("Ctrl+N")

newPlaylistAction.triggered.connect(createPlaylist)
renamePlaylistAction.triggered.connect(renamePlaylist)
addShownToPlaylistAction.triggered.connect(addShownSongsToPlaylist)

playListMenu.addAction(newPlaylistAction)
playListMenu.addAction(renamePlaylistAction)
playListMenu.addSeparator()
playListMenu.addAction(addShownToPlaylistAction)

#----------------------------------
#--------- Volume-Frame ----------
#----------------------------------
volumeWidget = QWidget(mainWidget)
volumeLayout = QVBoxLayout()

volIconList = [
	QPixmap(rscDir+"/volumeMute.png"),
	QPixmap(rscDir+"/volumeLow.png"),
	QPixmap(rscDir+"/volumeMiddle.png"),
	QPixmap(rscDir+"/volumeHigh.png"),
	QPixmap(rscDir+"/volumeVeryHigh.png")
]

volumeSlider = QSlider(Qt.Orientation.Vertical, volumeWidget)
volumeSlider.setRange(0, 100)
volumeSlider.setValue(curVolume)

volumeIcon = QLabel(volumeWidget)
volumeIcon.setPixmap(volIconList[ceil(curVolume/25)])

volumeSlider.valueChanged.connect(lambda: volumeEvent(volumeSlider.value()))

volumeLayout.addWidget(volumeSlider, alignment=Qt.AlignmentFlag.AlignHCenter)
volumeLayout.addWidget(volumeIcon, alignment=Qt.AlignmentFlag.AlignHCenter)

volumeWidget.setLayout(volumeLayout)

#----------------------------------
#---------- Search-Frame ----------
#----------------------------------
filterWidget = QWidget(mainWidget)
filterLayout = QGridLayout()

clearSearchBtn = QPushButton(filterWidget, text="Reset Filters")
clearSearchBtn.setMaximumHeight(100)
clearSearchBtn.setFont(QFont("Arial", 10))
clearSearchBtn.setStyleSheet("background-color: "+bg2)

searchLbl = QLabel("Search", filterWidget)
searchField = QLineEdit(filterWidget)
searchField.setStyleSheet("background-color: "+bg2)
searchField.setFont(QFont("Arial", 10))

artistListLbl = QLabel("Artist", filterWidget)
artistListBox = QComboBox(filterWidget)
artistListBox.setMaximumHeight(25)
artistListBox.setMinimumHeight(25)
artistListBox.setMaxVisibleItems(20)
artistListBox.setFont(QFont("Arial", 10))
artistListBox.setStyleSheet("background-color: "+bg2)
artistListBox.addItem("-- None Selected --")

albumListLbl = QLabel("Album", filterWidget)
albumListBox = QComboBox(filterWidget)
albumListBox.setMaximumHeight(25)
albumListBox.setMinimumHeight(25)
albumListBox.setMaxVisibleItems(20)
albumListBox.setFont(QFont("Arial", 10))
albumListBox.setStyleSheet("background-color: "+bg2)
albumListBox.addItem("-- None Selected --")

playListListLbl = QLabel("Playlist", filterWidget)
playListListBox = QComboBox(filterWidget)
playListListBox.setMaximumHeight(25)
playListListBox.setMinimumHeight(25)
playListListBox.setMaxVisibleItems(20)
playListListBox.setFont(QFont("Arial", 10))
playListListBox.setStyleSheet("background-color: "+bg2)
playListListBox.addItem("-- None Selected --")

redXIcon = QIcon(rscDir+"/redX.png")
redXPressedIcon = QIcon(rscDir+"/redXPressed.png")

def delCurPlayBtnPressed():
	delCurPlaylistBtn.setIcon(redXPressedIcon)

def delCurPlayBtnReleased():
	delCurPlaylistBtn.setIcon(redXIcon)


delCurPlaylistBtn = QPushButton(redXIcon, "", filterWidget)
delCurPlaylistBtn.setFixedSize(QSize(25, 25))
delCurPlaylistBtn.setIconSize(QSize(25, 25))
delCurPlaylistBtn.pressed.connect(delCurPlayBtnPressed)
delCurPlaylistBtn.released.connect(delCurPlayBtnReleased)
delCurPlaylistBtn.clicked.connect(delCurPlaylist)


searchField.textChanged.connect(searchEvent)
clearSearchBtn.clicked.connect(clearFilters)
artistListBox.currentTextChanged.connect(artistFilterEvent)
albumListBox.currentTextChanged.connect(albumFilterEvent)
playListListBox.currentTextChanged.connect(playlistFilterEvent)

filterLayout.addWidget(searchLbl, 0, 0)
filterLayout.addWidget(searchField, 1, 0, 1, 5)
filterLayout.addWidget(clearSearchBtn, 0, 5, 2, 2)
filterLayout.addWidget(artistListLbl, 2, 0)
filterLayout.addWidget(artistListBox, 3, 0, 1, 2)
filterLayout.addWidget(albumListLbl, 2, 2)
filterLayout.addWidget(albumListBox, 3, 2, 1, 2)
filterLayout.addWidget(playListListLbl, 2, 4)
filterLayout.addWidget(playListListBox, 3, 4, 1, 2)
filterLayout.addWidget(delCurPlaylistBtn, 3, 6, 1, 1)

filterLayout.setColumnStretch(0, 1)
filterLayout.setColumnStretch(1, 1)
filterLayout.setColumnStretch(2, 1)
filterLayout.setColumnStretch(3, 1)
filterLayout.setColumnStretch(4, 1)
filterLayout.setColumnStretch(5, 1)

filterWidget.setLayout(filterLayout)

#----------------------------------
#---------- Song-List -------------
#----------------------------------
class SongTableSortFilterProxyModel(QSortFilterProxyModel):
	def __init__(self):
		super().__init__()

	def data(self, index: QModelIndex, role: Qt.ItemDataRole=Qt.ItemDataRole.DisplayRole):
		if (index.column() == 3 and role == Qt.ItemDataRole.TextAlignmentRole):
			return Qt.AlignmentFlag.AlignCenter
		else:
			return QSortFilterProxyModel.data(self, index, role)

	def filterAcceptsRow(self, source_row: int, source_parent):
		obj = [
			self.sourceModel().data(self.sourceModel().index(source_row, 0)),
			self.sourceModel().data(self.sourceModel().index(source_row, 1)),
			(self.sourceModel().data(self.sourceModel().index(source_row, 2)) or "")
		]
		if source_row == self.sourceModel().rowCount()-1:
			QTimer.singleShot(0, tableViewFilterEnded)
		if obj[0] == None or obj[1] == None or obj[2] == None:
			return True
		if filters["search"] and not (hasSearchWords(" ".join(obj))):
			return False
		if filters["artist"] and not (filters["artist"] in obj[1]):
			return False
		if filters["album"] and not (filters["album"] in obj[2]):
			return False
		if filters["playlist"] and not (obj[0]+" - "+obj[1] in playlists[filters["playlist"]]):
			return False
		
		return True

class SongTable(QTableView):
	def __init__(self, parent):
		super().__init__(parent=parent)

	def contextMenuEvent(self, e: QContextMenuEvent):
		self.menu = QMenu(self)
		sourceIndex = filterSongTable.mapToSource(self.indexAt(e.pos()))
		row = sourceIndex.row()
		if row == -1: return
		songname = songTableModel.data(songTableModel.index(row, 0))+" - "+songTableModel.data(songTableModel.index(row, 1))
		addToPlaylistMenu = QMenu("Add To Playlist", self.menu)
		removeFromPlayListMenu = QMenu("Remove From Playlist", self.menu)
		actions = {}
		for p in playlists:
			if songname in playlists[p]:
				actions[p] = QAction(p, addToPlaylistMenu)
				removeFromPlayListMenu.addAction(actions[p])
				actions[p].triggered.connect(lambda checked, pl=p: removeFromPlaylist(pl, songname))
			else:
				actions[p] = QAction(p, removeFromPlayListMenu)
				addToPlaylistMenu.addAction(actions[p])
				actions[p].triggered.connect(lambda checked, pl=p: addToPlaylist(pl, songname))

		self.menu.addMenu(addToPlaylistMenu)
		self.menu.addMenu(removeFromPlayListMenu)

		self.menu.popup(QCursor.pos())

		

songTableModel = QStandardItemModel(0, 3)
songTableModel.setHorizontalHeaderLabels(["Title", "Artist", "Album", "Track", "Shuffle"])

filterSongTable = SongTableSortFilterProxyModel()
filterSongTable.setSourceModel(songTableModel)
filterSongTable.setFilterKeyColumn(-1)

tableWidth = 800
songListBox = SongTable(mainWidget)
songListBox.setMinimumHeight(400)
songListBox.setMaximumHeight(1000)
songListBox.setMaximumWidth(tableWidth)
songListBox.setMinimumWidth(tableWidth)
songListBox.horizontalHeader().setStyleSheet("::section{background:"+bg1+";}")
songListBox.verticalHeader().hide()
songListBox.setStyleSheet("background-color:"+bg2+";color:"+textCol+";"
	"selection-background-color:"+selectCol+";")

songListBox.setSelectionBehavior(QTableView.SelectRows)
songListBox.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
songListBox.setSortingEnabled(True)

filterSongTable.setDynamicSortFilter(False)
songListBox.setModel(filterSongTable)
filterSongTable.setDynamicSortFilter(True)
filterSongTable.sort(0, Qt.SortOrder.AscendingOrder)

header = songListBox.horizontalHeader()
header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
songListBox.setColumnWidth(1, int(tableWidth/4))
songListBox.setColumnWidth(2, int(tableWidth/3.5))
songListBox.setColumnWidth(3, int(tableWidth/10))
songListBox.hideColumn(3)
songListBox.hideColumn(4)

songListBox.selectionModel().currentRowChanged.connect(songSelectedEvent)
header.sortIndicatorChanged.connect(sortChangedScroll)

#----------------------------------
#---------- Current-Song ----------
#----------------------------------
curSongLbl = QLabel(curSongname, mainWidget)
curSongLbl.setFont(QFont("Arial", 10))
curSongLbl.setContentsMargins(20, 10, 0, 0)

#----------------------------------
#----------- Time-Frame -----------
#----------------------------------
timeWidget = QWidget(mainWidget)
timeLayout = QGridLayout()

playTimeLbl = QLabel(timeWidget, text="00:00:00")
playTimeLbl.setFont(QFont("Arial", 9))
songLenLbl = QLabel(timeWidget, text="00:00:00")
songLenLbl.setFont(QFont("Arial", 9))

timeSlider = QSlider(Qt.Orientation.Horizontal, timeWidget)
timeSlider.setRange(0, 100)
timeSlider.setValue(0)
timeSlider.valueChanged.connect(lambda: timeSlideEvent(timeSlider.value()))

timeLayout.addWidget(playTimeLbl, 0, 0, alignment=Qt.AlignmentFlag.AlignLeft)
timeLayout.addWidget(songLenLbl, 0, 1, alignment=Qt.AlignmentFlag.AlignRight)
timeLayout.addWidget(timeSlider, 1, 0, 1, 2)

timeWidget.setLayout(timeLayout)

#----------------------------------
#---------- Button-Frame ----------
#----------------------------------
buttonWidget = QWidget(mainWidget)
buttonWidget.setFixedSize(400, 70)
buttonLayout = QHBoxLayout()

if not isdir(rscDir):
	print("can't find ressources")
	exit()

shuffleBtnImg = QIcon(rscDir+"/ShuffleBtn.png")
backBtnImg = QIcon(rscDir+"/BackBtn.png")
playBtnImg = QIcon(rscDir+"/PlayBtn.png")
pauseBtnImg = QIcon(rscDir+"/PauseBtn.png")
nextBtnImg = QIcon(rscDir+"/NextBtn.png")


shuffleBtn = QPushButton(shuffleBtnImg, '', buttonWidget)
backBtn = QPushButton(backBtnImg, '', buttonWidget)
playPauseBtn = QPushButton(playBtnImg, '', buttonWidget)
nextBtn = QPushButton(nextBtnImg, '', buttonWidget)

btnStyle = "background-color: "+bg2+"; border-radius: 25px"

btnSize = 50

shuffleBtn.setFixedSize(btnSize, btnSize)
backBtn.setFixedSize(btnSize, btnSize)
playPauseBtn.setFixedSize(btnSize, btnSize)
nextBtn.setFixedSize(btnSize, btnSize)

shuffleBtn.setStyleSheet(btnStyle)
backBtn.setStyleSheet(btnStyle)
playPauseBtn.setStyleSheet(btnStyle)
nextBtn.setStyleSheet(btnStyle)

iconSize = 35

shuffleBtn.setIconSize(QSize(iconSize, iconSize))
backBtn.setIconSize(QSize(iconSize, iconSize))
playPauseBtn.setIconSize(QSize(iconSize, iconSize))
nextBtn.setIconSize(QSize(iconSize, iconSize))

shuffleBtn.clicked.connect(shuffleSongs)
backBtn.clicked.connect(prevSong)
playPauseBtn.clicked.connect(playPauseSong)
nextBtn.clicked.connect(nextSong)

shuffleShortcut = QShortcut(QKeySequence("r"), mainWidget)
backShortcut = QShortcut(QKeySequence("Left"), mainWidget)
playPauseShortcut = QShortcut(QKeySequence("Space"), mainWidget)
nextShortcut = QShortcut(QKeySequence("Right"), mainWidget)
volumeUpShortcut = QShortcut(QKeySequence("Up"), mainWidget)
volumeDownShortcut = QShortcut(QKeySequence("Down"), mainWidget)

# shuffleShortcut.activated.connect(shuffleList)
backShortcut.activated.connect(prevSong)
playPauseShortcut.activated.connect(playPauseSong)
nextShortcut.activated.connect(nextSong)
volumeUpShortcut.activated.connect(lambda: volumeEvent(curVolume+10))
volumeDownShortcut.activated.connect(lambda: volumeEvent(curVolume-10))

buttonLayout.addWidget(shuffleBtn)
buttonLayout.addWidget(backBtn)
buttonLayout.addWidget(playPauseBtn)
buttonLayout.addWidget(nextBtn)
buttonLayout.setContentsMargins(0,10,0,10)
buttonLayout.setSpacing(0)

buttonWidget.setLayout(buttonLayout)

#----------------------------------
#--------- Player-Layout ----------
#----------------------------------
playerWidget = QWidget(mainWidget)
playerLayout = QGridLayout()
#        0              1               2
#      ___________________________________
#  0  |_________________________________  |  0
#  1  |     |          FILTERS          | |  1
#     |_____|___________________________| |
#  2  |     |                           | |  2
#     |  V  |         SONGLIST          | |
#     |  O  |___________________________| |
#  3  |  L  |         SONGNAME          | |  3
#     |  U  |___________________________| |
#  4  |  M  |           TIME            | |  4
#     |_____|___________________________| |
#  5  |     |          BUTTONS          | |  5
#     |_____|___________________________| |
#  6  |___________________________________|  6
#
#        0              1               2

playerLayout.setColumnMinimumWidth(0, 70)
playerLayout.setColumnMinimumWidth(2, 20)
playerLayout.setRowMinimumHeight(0, 10)
playerLayout.setRowMinimumHeight(6, 10)

playerLayout.addWidget(volumeWidget, 2, 0, 3, 1)
playerLayout.addWidget(filterWidget, 1, 1)
playerLayout.addWidget(songListBox,  2, 1)
playerLayout.addWidget(curSongLbl,   3, 1)
playerLayout.addWidget(timeWidget,   4, 1)
playerLayout.addWidget(buttonWidget, 5, 1,       alignment=Qt.AlignmentFlag.AlignHCenter)

playerWidget.setLayout(playerLayout)

#----------------------------------
#---------- Main-Layout -----------
#----------------------------------
mainLayout = QStackedLayout()

mainLayout.setStackingMode(0)

mainLayout.addWidget(playerWidget)
# mainLayout.addWidget(settingsWidget)

mainLayout.setCurrentWidget(playerWidget)

mainWidget.setLayout(mainLayout)

#-------------------------------------------------------------------
#------------------------- Load Saved Data -------------------------
#-------------------------------------------------------------------
#structure:
#   -lastSongPlaying
#	-paused
#	-songLen
#   -time
#   -volume
#   -filters:
#       -search
#       -artist
#       -album
#   -theme:
#       -textCol
#       -bg1
#       -bg2

def loadConfig():
	global curSongname, paused, curSongLen, curTimePos, curVolume
	if not isfile(iniDir+"/config.txt"): return

	with open(iniDir+"/config.txt", "r", encoding="utf-8") as f:
		file = f.read()
		if not file: return

		lines = f.read().split("\n")
		if not len(lines) == 8: return

		curSongname = lines[0]
		curSongLbl.setText(curSongname)

		paused = bool(lines[1])

		curSongLen = float(lines[2] or 100)
		songLenLbl.setText(time.strftime('%H:%M:%S', time.gmtime(int(curSongLen))))
		timeSlider.setRange(0, int(curSongLen))

		curTimePos = int(lines[3] or 0)
		timeSlider.setValue(curTimePos)
		playTimeLbl.setText(time.strftime('%H:%M:%S', time.gmtime(int(curTimePos))))

		curVolume = int(lines[4] or 50)
		volumeSlider.setValue(curVolume)

		filters["search"] = lines[5]
		filters["artist"] = lines[6]
		filters["album"] = lines[7]
		if filters["search"]:
			searchField.setText(filters["search"])
		if filters["artist"]:
			artistList.append(filters["artist"])
			artistListBox.addItem(filters["artist"])
			artistListBox.setCurrentText(filters["artist"])
		elif filters["album"]:
			albumList.append(filters["album"])
			albumListBox.addItem(filters["album"])
			albumListBox.setCurrentText(filters["album"])

def loadPaths():
	global folders, paths, removedPaths
	if not isfile(iniDir+"/paths.txt"): return

	with open(iniDir+"/paths.txt", "r", encoding="utf-8") as f:
		file = f.read()
		if not file: return

		if file[0] == "\n":
			if file[-1] == "\n":
				folders = file[1:-1].split("\n")
			else:
				parts = file[1:].split("\n\n")
				folders = parts[0].split("\n")
				removedPaths = parts[1].split("\n")
		elif file[-1] == "\n":
			parts = file[:-1].split("\n\n")
			paths = parts[0].split("\n")
			folders = parts[1].split("\n")
		else:
			parts = file.split("\n\n")
			paths = parts[0].split("\n")
			folders = parts[1].split("\n")
			removedPaths = parts[2].split("\n")
		
		ps = []
		ps.extend(paths)
		for f in folders:
			ps.extend([f+"/"+p for p in listdir(f)])
		for rp in removedPaths:
			if rp in ps:
				ps.remove(rp)
			else:
				removedPaths.remove(rp)
		emitAddSong.addSongs(ps)

def loadPlaylists():
	global playlists
	if not isfile(iniDir+"/playlists.txt"): return

	with open(iniDir+"/playlists.txt", "r", encoding="utf-8") as f:
		file = f.read()
		if not file: return

		playlistParts = [part for part in file.split("\n\n") if part]
		playlistParts = [part.split("\n") for part in playlistParts]
		playlists = {part[0]: [p for p in part[1:] if p] for part in playlistParts}
		for playlist in playlists:
			playListListBox.addItem(playlist)

if isdir(iniDir):
	loadConfig()
	loadPaths()
	loadPlaylists()		
else:
    print("Failed to load resources form '"+iniDir+"'")
    exit()

#-------------------------------------------------------------------
#---------------------------- Main-Loop ----------------------------
#-------------------------------------------------------------------
window.show()

app.exec()

#-------------------------------------------------------------------
#---------------------------- Save Data ----------------------------
#-------------------------------------------------------------------
# save configs
s = ""
s += str(curSongname)+"\n"
s += str(paused and "1" or "")+"\n"
s += str(curSongLen)+"\n"
s += str(curTimePos)+"\n"
s += str(curVolume)+"\n"
s += str(filters["search"])+"\n"
s += str(filters["artist"])+"\n"
s += str(filters["album"])

if isfile(iniDir+"/config.txt"):
    with open(iniDir+"/config.txt", "w", encoding="utf-8") as f:
        f.write(s)
else:
    with open(iniDir+"/config.txt", "x", encoding="utf-8") as f:
        f.write(s)

# save paths
s = ""
for p in paths:
	s += p+"\n"
s += "\n"
for f in folders:
	s += f+"\n"

for rp in removedPaths:
	s += "\n"+rp

if isfile(iniDir+"/paths.txt"):
    with open(iniDir+"/paths.txt", "w", encoding="utf-8") as f:
        f.write(s)
else:
    with open(iniDir+"/paths.txt", "x", encoding="utf-8") as f:
        f.write(s)

#save playlists
s = ""
for playlist, songs in playlists.items():
	s += playlist+"\n"
	for song in songs:
		s += song+"\n"
	s += "\n"
s = s[:-2]

if isfile(iniDir+"/playlists.txt"):
    with open(iniDir+"/playlists.txt", "w", encoding="utf-8") as f:
        f.write(s)
else:
    with open(iniDir+"/playlists.txt", "x", encoding="utf-8") as f:
        f.write(s)