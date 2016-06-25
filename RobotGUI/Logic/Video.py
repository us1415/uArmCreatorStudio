import cv2
from threading             import Thread, RLock
from RobotGUI.Logic.Global import printf, FpsTimer


def getConnectedCameras():
    tries = 10
    cameraList = []

    for i in range(0, tries):
        testCap = cv2.VideoCapture(i)

        if testCap.isOpened():
            cameraList.append(i)
            testCap.release()

    return cameraList


class VideoStream:
    """
    VideoStream is a threaded video-getter that doubles as a processing unit for repetative computer vision tasks.
    Some computer vision tasks require real-time tracking and fast results. With this system, you can add "tasks"
    for the VideoStream to complete.

    For example, if you are tracking objects, an "objectTracker" filter will be added to the VideoStream

    Repetative tasks include:
        - Adding filters to videoStreams (like contours, keypoints, or outlining tracked objects)
        - Getting tracked objects
    """

    def __init__(self, fps=24):
        self.frameLock   = RLock()  # Lock for any frame get/copy/read operations
        self.filterLock  = RLock()  # Lock for any filtering operations, added under self.addFilter()
        self.workLock    = RLock()  # Lock for any "Work" functions, added under self.addWork()

        self.running     = False
        self.setCamera   = None     # When this is a number and videoThread is on, it will attempt to setNewCamera(new)
        self.paused      = True

        self.cameraID    = None
        self.fps         = fps
        self.cap         = None  # An OpenCV capture object
        self.dimensions  = None  # Will be [x dimension, y dimension]


        self.frame       = None
        self.frameList   = []    # Used in computer vision tasks, this is a list of the last 5 frames (unfiltered)
        self.frameCount  = 0     # Used in waitForNewFrame()

        self.filterFrame = None  # A frame that has gone under all the filters in the self.filters list
        self.filterList  = []    # A list of functions that all input a frame and output a modified frame.
        self.workList    = []    # A list of functions that all input a frame, but don't output anything.

        self.mainThread  = None


    def setNewCamera(self, cameraID):
        # Activate a trigger in the mainThread to turn on the camera
        # Connecting to camera is run inside the thread because it's a lengthy process (over 1 second)
        # This would lock up the GUI

        # Make sure the mainThread is running, so that this trigger will work
        if self.setCamera is None:
            self.startThread()
            self.setCamera = cameraID
        else:
            printf("VideoStream.setNewCamera(): ERROR: Tried to set camera while camera was already being set!")

    def setPaused(self, value):
        # Tells the main frunction to grab more frames
        if value is False:  # If you want to play video, make sure everything set for that to occur
            # if not self.connected():
            #     self.setNewCamera(self.cameraID)

            if self.mainThread is None:
                self.startThread()

        self.paused = value

    def connected(self):
        # Returns True or False if there is a camera successfully connected
        if self.cap is None:        return False
        if not self.cap.isOpened(): return False
        return True

    def setFPS(self, fps):
        # Sets how often the main function grabs frames (Default: 24)
        self.fps = fps


    def startThread(self):
        if self.mainThread is None:
            self.running = True
            self.mainThread = Thread(target=self.__videoThread)
            self.mainThread.start()
        else:
            printf("VideoStream.startThread(): ERROR: Tried to create mainThread, but mainThread already existed.")

    def endThread(self):
        self.running = False

        if self.mainThread is not None:
            printf("VideoStream.endThread(): Ending main thread")
            self.mainThread.join(500)
            self.mainThread = None

        if self.cap is not None:
            printf("VideoStream.endThread(): Thread ended. Now gracefully closing Cap")
            self.cap.release()

    def __videoThread(self):
        """"
            A main thread that focuses soley on grabbing frames from a camera, limited only by self.fps
            Thread is created at startThread, which can be called by setPaused
            Thread is ended only at endThread
        """

        self.frameList = []

        fpsTimer = FpsTimer(self.fps)
        printf("VideoStream.videoThread(): Starting videoStream thread.")
        while self.running:
            fpsTimer.wait()
            if not fpsTimer.ready():       continue
            if self.setCamera is not None: self.__setNewCamera(self.setCamera)
            if self.paused:                continue
            if self.cap is None:           continue


            # Get a new frame
            ret, newFrame = self.cap.read()

            if not ret:  # If a frame was not successfully returned
                printf("VideoStream.videoThread(): ERROR while reading frame from Camera: ", self.cameraID)
                self.__setNewCamera(self.cameraID)
                cv2.waitKey(1000)
                continue


            # Do frame related work
            with self.frameLock:
                self.frame = newFrame

                # Add a frame to the frameList that records the 5 latest frames for Vision uses
                self.frameList.insert(0, self.frame.copy())
                # print("len", len(self.frameList), "Curr frames: ", [id(frame) for frame in self.frameList])
                while len(self.frameList) > 10:
                    del self.frameList[-1]

                # Keep track of new frames by counting them. (100 is an arbitrary number)
                if self.frameCount >= 100:
                    self.frameCount = 0
                else:
                    self.frameCount += 1


            # Run any work functions that must be run. Expect no results. Work should be run before filters.
            if len(self.workList) > 0:
                with self.workLock:
                    for workFunc in self.workList:
                        workFunc(self.frame)



            # Run any filters that must be run, save the results in self.filterFrame
            if len(self.filterList) > 0:
                with self.filterLock:
                    filterFrame = self.getFrame()
                    for filterFunc in self.filterList:
                        filterFrame = filterFunc(filterFrame)
                    self.filterFrame = filterFrame

                    # cv2.imshow('myframe', self.filterFrame )
                    # cv2.waitKey(1)
            else:
                self.filterFrame = self.frame



        printf("VideoStream.videoThread(): VideoStream Thread has ended")

    def __setNewCamera(self, cameraID):
        # Set or change the current camera to a new one
        printf("VideoStream.setNewCamera(): Setting camera to cameraID ", cameraID)


        # Gracefully close the current capture if it exists
        if self.cap is not None: self.cap.release()


        # Set the new cameraID and open the capture
        self.cap = cv2.VideoCapture(cameraID)


        # Check if the cap was opened correctly
        if not self.cap.isOpened():
            printf("VideoStream.setNewCamera(): ERROR: Camera not opened. cam ID: ", cameraID)
            self.cap.release()
            self.dimensions = None
            self.cap        = None
            self.setCamera  = None
            return False


        # Try getting a frame and setting self.dimensions. If it does not work, return false
        ret, frame = self.cap.read()
        if ret:
            self.dimensions = [frame.shape[1], frame.shape[0]]
        else:
            printf("VideoStream.setNewCamera(): ERROR ERROR: Camera could not read frame. cam ID: ", cameraID)
            self.cap.release()
            self.dimensions = None
            self.cap        = None
            self.setCamera  = None
            return False

        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 3)


        # Since everything worked, save the new cameraID
        self.setCamera = None
        self.cameraID  = cameraID
        return True


    # Called from outside thread
    def getFrame(self):
        # Returns the latest frame grabbed from the camera
        # with self.frameLock:
        if self.frame is not None:
            return self.frame.copy()
        else:
            return None

    def getFilteredWithID(self):
        # with self.frameLock:
        if self.filterFrame is not None:
            # Frames are copied because they are generally modified.
            return self.frameCount, self.filterFrame.copy()
        else:
            return None, None

    def getFrameList(self):
        """
        Returns a list of the last x frames
        This is used in functions like Vision.getMotion() where frames are compared
        with past frames
        """
        with self.frameLock:
            return list(self.frameList)



    def addFilter(self, filterFunc):
        # Add a filter to put on top of the self.filteredFrame each round
        with self.filterLock:
            if filterFunc in self.filterList: return

            self.filterList.append(filterFunc)

    def addWork(self, workFunc):
        # Add some function that has to be run each round. Processing is done after frame get, but before filtering.
        with self.workLock:
            if workFunc in self.workList: return

            self.workList.append(workFunc)

    def removeWork(self, workFunc):
        # Remove a function from the workList

        with self.workLock:
            # Make sure the function is actually in the workList
            if workFunc not in self.workList: return

            self.workList.remove(workFunc)

    def removeFilter(self, filterFunc):
        with self.filterLock:
            # Make sure the function is actually in the workList
            if filterFunc not in self.filterList: return

            self.filterList.remove(filterFunc)

    def waitForNewFrame(self):
        lastFrame = self.frameCount
        while self.frameCount == lastFrame: pass













