#!/usr/bin/python
################################################################################
#
# Tool to generate laser cutter tests
#
# Creates G-Code to test Laser Cutter performance along any two of these three
#  dimentions (the third being held constant for the test):
#  * Power: the strength of the laser (based on PWM modulation)
#  * Speed: rate at which the laser moves while cutting
#  * Focus: Z-axis distance from surface to be cut
# The values for the test dimensions are given as string that represents a
#  3-tuple that contains a range (defined by a colon-separated pair of min and
#  max float values), and the number of steps to generate within the given range.
# A test dimension string can be "fixed" in that it only generates one value.
#  This can be done by making both the min and max values the same, or by making
#  the count be one (in which case only the min value is used throughout -- as
#  a range of tests is always generated starting with the min value.
# A warning is generated if the range and counts aren't consistent with respect
#  to whether they make the test dimension fixed or not.
# A count value of one will generate a single test using the min value, a count
#  of two will generate tests using the min and the max values, a count of
#  greater than two will generate tests that include both the min and the max
#  values as well as values every ((max - min) / (count - 1)) interval between
#  them.
# Values must be given for all three test dimensions, however, from one to all
#  three of them can be fixed -- i.e., each run can generate tests which vary
#  zero, one, or two of the test dimensions.
# If all three values are given as scalars, then a single cut is made, using the
#  given values for power, speed, and focus.
# If two of the three values are given as scalars, then a single row of test
#  cuts will be made with two of the values held constant and the third varied
#  across the given range (in the given number of increments).
# If only one of the values is given as scalar, then multiple rows of test cuts
#  are created, with the test dimension range with the largest increment value
#  being the columns and the other being the rows.
# The test pattern consists of a set of vertical lines cut from left to right
#  in rows.  Multiple groups of tests are cut as rows that are cut on top of the
#  prior test row.
# As more tests can be done in the X axis than in the Y (as the test lines are
#  cut vertically), if two dimensions are given as ranges, then the one with the
#  largest increment is assigned to the X axis.
# N.B. One should choose the values for the test ranges and increments in such
#  a way as to give the greatest variation along the dimension of greater
#  interest, and see that that gets assigned to the X axis.
# This assumes that the laser starts at the lower right hand corner of the
#  Shapeoko(2) -- i.e., the origin/(0,0,0) location.  The G-Code will first move
#  the laser to the starting (i.e., min) Z axis location, and then begin the
#  test cuts.
#
# Can use GCode simulator @ https://nraynaud.github.io/webgcode/ to see output.
#
################################################################################

#### TODO make option to add comments (in "()" chars) to GCode lines

import argparse
import datetime
import os
import sys


def makeInputStr(minVal, maxVal, count):
    """
    Create a default input string for a given test dimension.
    """
    return "{0}:{1},{2}".format(minVal, maxVal, count)


class GcodeOutput(object):
    """
    Encapsulates all the supported means of emitting GCodes.
    Currently can write to a file or stream to GRBL.
    """
    #### TODO make this Thread-safe as it's not
    # Supported output modes
    OUTPUT_MODES = ('FILE', 'GRBL')

    def __init__(self, mode, file_):
        """
        Take the output mode (currently, you can emit to a file/stdout or
         drive the Arduino-based GRBL controller), and the name of the file
         to write to (for file mode) or the port to which the GRBL controller
         is attached and instantiate an output object that can be used to
         batch up output and then emit it
        """
        self.gcodes = []
        mode = mode.upper()
        if mode not in GcodeOutput.OUTPUT_MODES:
            raise ValueError("Invalid output mode {0}, must be one of {1}".
                             format(mode, GcodeOutput.OUTPUT_MODES))
        self.mode = mode
        if self.mode == 'FILE':
            if file_ == '-':
                self.output = sys.stdout
            else:
                try:
                    self.output = open(file_, 'w')
                except Exception as ex:
                    raise ValueError("Unable to write output to {0}; {1}".
                                     format(file_, ex))
            t = datetime.datetime.now()
            p = os.path.basename(sys.argv[0])
            self.header = "( Generated by: {0} @ {1} )\n".format(p, t)
        elif self.mode == 'GRBL':
            pass   #### FIXME implement this

    def hdr(self, str_):
        """
        Add the given string to the header block that is to be emitted at the
         start of the output in FILE mode.
        """
        if verbosity > 0:
            sys.stderr.write("{0}\n".format(str_))
        if comment and self.mode == 'FILE':
            if not self.header:
                raise RuntimeError("Cannot add to headers after first emit")
            self.header += "( {0} )\n".format(str_)

    def compose(self, gcodes):
        """
        Build up the GCodes to be (optionally post-processed) and emmited later
        """
        #### TODO see if there are checks or modifications needed on compose
        if verbosity > 1:
            print gcodes
        self.gcodes += gcodes

    def getLen(self):
        """
        Return the current number of GCodes in the buffer waiting to be post-
         processed or emitted.
        """
        return len(self.gcodes)

    def postProcess(self):
        """
        Run whatever post-processing is desired on the current collection of
        GCodes.
        """
        pass    #### FIXME implement this

    def emit(self):
        """
        Emit the current contents of the GCode buffer in the chosen method, and
         leave the buffer empty.
        """
        if self.mode == 'FILE':
            if self.header:
                self.output.write(self.header)
                self.header = None
            outStr = "\n".join(self.gcodes)
            self.output.write(outStr)
        elif self.mode == 'GRBL':
            pass    #### FIXME
        self.gcodes = []


class InputArgumentError(ValueError):
    """
    Exception to indicate bad input string.
    """
    pass


class Dimension(object):
    """
    Base class for the three test dimensions -- i.e., speed, power, and
     distance.
    Takes a string of the form: <min>:<max>,<cnt> and returns an object
     that holds the validated state of that input.
    Throws ValueError if bad input given.
    """
    def __init__(self, inputStr):
        self.name = "UNINITIALIZED"
        self.val = None
        try:
            rangeStr, countStr = inputStr.split(',')
            minStr, maxStr = rangeStr.split(":")
            self.minVal = float(minStr)
            self.maxVal = float(maxStr)
            self.count = int(countStr)
        except Exception:
            raise
        if ((self.minVal == self.maxVal and self.count != 1) or
                (self.minVal != self.maxVal and self.count == 1)):
            sys.stderr.write("Warning: inconsistent fixed spec {0}\n".
                             format(inputStr))
        if self.count > 1:
            self.incr = (self.maxVal - self.minVal) / (self.count - 1)
        else:
            self.incr = 0.0
        self.fixed = self.count == 1 or self.minVal == self.maxVal
        self.reset()

    def reset(self):
        """
        Reset the next value counter to the start and the current value to
         minVal.
        """
        self.indx = 0
        self.val = self.minVal

    def next(self):
        """
        Return the next value in the range and bump the counter 'indx'.
        Returns minVal (and doesn't bump the value) if the dimension is fixed.
        Throws exception if ask for more values after having reached the max.
        (The caller should be looping on the count and not relying on this
        for loop termination conditions.)
        Compute next val based on count (as opposed to adding 'incr') to avoid
         accumulating errors.
        """
        if self.fixed:
            return self.minVal
        self.indx += 1
        if self.indx >= self.count:
            raise ValueError("Asked for too many next values")
        self.val = round(((self.indx * ((self.maxVal - self.minVal) /
                                        (self.count - 1))) + self.minVal), 2)
        return self.val

    def __str__(self):
        incr = "%.1f" % round(self.incr, 1)
        return "{0}: \tmin = {1}, \tmax = {2}, \tcount = {3}, \tincr = {4}, \t{5}". \
            format(self.name, self.minVal, self.maxVal, self.count, incr,
                   ('Varies', 'Fixed')[self.fixed])

    def __repr__(self):
        return self.__str__()


class SpeedDim(Dimension):
    """
    Encapsulates the Speed test dimension.
    This defines the speed (in mm/min) that the laser moves during cuts.
    """
    def __init__(self, speedStr):
        self.name = "Speed"
        try:
            super(self.__class__, self).__init__(speedStr)
        except Exception:
            raise
        if self.minVal < TestParams.MIN_XY_SPEED:
            raise InputArgumentError("Minimum speed to slow (< {0})".
                                     format(TestParams.MIN_XY_SPEED))
        if self.maxVal > TestParams.MAX_XY_SPEED:
            raise InputArgumentError("Maximum speed to fast (> {0})".
                                     format(TestParams.MAX_XY_SPEED))


class PowerDim(Dimension):
    """
    Encapsulates the Power test dimension.
    This is the PWM value that defines the strength of the laser.
    In the case of the J-Tech laser with the Arduino GRBL, this value
     ranges from 0 (i.e., off) to 10000 (i.e., max power) -- this is
     all defined in the GRBL source code constants.
    """
    def __init__(self, powerStr):
        self.name = "Power"
        try:
            super(self.__class__, self).__init__(powerStr)
        except Exception:
            raise
        if self.minVal < TestParams.MIN_POWER:
            raise InputArgumentError("Minimum power too low (< {0})".
                                     format(TestParams.MIN_POWER))
        if self.maxVal > TestParams.MAX_POWER:
            raise InputArgumentError("Maximum power too high (> {0})".
                                     format(TestParams.MIN_POWER))


class DistanceDim(Dimension):
    """
    Encapsulates the Distance test dimension.
    This is the Z-axis distance from the cutting surface (aka: focus).
    """
    def __init__(self, distanceStr):
        self.name = "Distance"
        try:
            super(self.__class__, self).__init__(distanceStr)
        except Exception:
            raise
        if self.minVal < TestParams.MIN_Z_DISTANCE:
            raise InputArgumentError("Minimum distance too close (< {0})".
                                     format(TestParams.MIN_Z_DISTANCE))
        if self.maxVal > TestParams.MAX_Z_DISTANCE:
            raise InputArgumentError("Maximum distance too far (> {0})".
                                     format(TestParams.MAX_Z_DISTANCE))


class Shapeoko2(object):
    """
    Encapsulates the specifics of a particular CNC machine.
    This is the Shapeoko2 with Acme Z axis and the J-Tech 3.8W Laser Diode.
    """
    # X-/Y-axis cutting speed constants (in mm/min)
    DEF_XY_SPEED = 750.0
    MIN_XY_SPEED = 100.0
    MAX_XY_SPEED = 5000.0

    # Power constants (in spindle RPM) -- J-Line 2.8W/GRBL 0.9+
    DEF_POWER = 1000.0
    MIN_POWER = 0.0
    MAX_POWER = 10000.0

    # Z-axis cutting distance constants (in mm)
    DEF_Z_DISTANCE = 10.0
    MIN_Z_DISTANCE = 10.0
    MAX_Z_DISTANCE = 100.0

    # Movement (non-cutting) speed in all axes
    XY_MOVE_SPEED = 4000.0
    Z_MOVE_SPEED = 400.0

    # Max distance in X that the test can span (in mm)
    MAX_X_DISTANCE = 150.0

    # Max distance in Y that the test can span (in mm)
    MAX_Y_DISTANCE = 150.0

    # Max distance in Z that the test can span (in mm)
    MAX_Z_DISTANCE = 50.0


class TestParams(Shapeoko2):
    """
    Encapsulates the parameters for the given tests on a specific machine type.
    """
    # width of laser cut (in mm)
    KERF = .2

    # Min/max distance between individual test lines in X (in mm)
    MIN_X_SPACING = 1.0
    MAX_X_SPACING = 10.0

    # Min/max distance between rows of test lines in Y (in mm)
    MIN_Y_SPACING = 5.0
    MAX_Y_SPACING = 10.0

    # Def height of test lines (in mm)
    DEF_LINE_HEIGHT = 20.0

    # Default test counts
    DEF_SPEED_COUNT = 1
    DEF_POWER_COUNT = 1
    DEF_DISTANCE_COUNT = 1

    def __init__(self, speedTuple, powerTuple, distanceTuple,
                 lineHeight=DEF_LINE_HEIGHT):
        try:
            self.speed = SpeedDim(speedTuple)
            self.power = PowerDim(powerTuple)
            self.distance = DistanceDim(distanceTuple)
        except Exception:
            raise
        self.lineHeight = lineHeight
        self.dims = [self.speed, self.power, self.distance]
        numDims = len(self.dims)
        self.varDims = [dim for dim in self.dims if not dim.fixed]
        self.numFixedDims = sum([self.speed.fixed, self.power.fixed,
                                 self.distance.fixed])
        self.numVarDims = numDims - self.numFixedDims

        if self.numVarDims >= numDims:
            # can't (effectively) plot three variable dimensions on 2D surface
            raise InputArgumentError("Too many free dimensions, at least one must be fixed")
        elif self.numVarDims < 2:
            # at most one variable dim, so just one row
            self.numRows = 1
            self.yDim = None
            if self.numVarDims == 1:
                # only one row along the one variable dim
                self.xDim = self.varDims[0]
                self.numCols = self.varDims[0].count
            else:
                # no variable dims, so just one test cut
                self.numCols = 1
                self.xDim = None
        else:
            # max count of all variable dims
            self.xDim = max(self.varDims, key=lambda item: item.count)

            # not the xDim, but the other variable one
            self.yDim = [dim for dim in self.varDims if dim != self.xDim][0]

            self.numRows = self.yDim.count
            self.numCols = self.xDim.count

        # increment to move X for each new column
        if self.numCols <= 1:
            self.xIncr = 0.0
        else:
            self.xIncr = self.MAX_X_DISTANCE / (self.numCols - 1)
            if (self.xIncr - self.KERF) < self.MIN_X_SPACING:
                raise InputArgumentError("Too many columns; reduce {0} count".
                                         format(self.xDim.name))
            if self.xIncr > self.MAX_X_SPACING:
                self.xIncr = self.MAX_X_SPACING

        # increment to move Y for each new row (from base of previous row)
        if self.numRows < 2:
            self.yIncr = 0.0
        else:
            self.yIncr = ((self.MAX_Y_DISTANCE - self.lineHeight) /
                          (self.numRows - 1))
            if (self.yIncr - self.lineHeight) < self.MIN_Y_SPACING:
                raise InputArgumentError("Too many rows; reduct count of {0}".
                                         format(self.yDim.name))
            if self.yIncr > self.MAX_Y_SPACING:
                self.yIncr = self.lineHeight + self.MAX_Y_SPACING

        # dimensions of complete test pattern
        if self.numCols > 1:
            self.width = (self.xIncr * (self.numCols - 1)) + self.KERF
        else:
            self.width = self.KERF
        if self.numRows > 1:
            self.height = (self.yIncr * (self.numRows - 1)) + self.lineHeight
        else:
            self.height = self.lineHeight

    def nextX(self):
        return self.xDim.next()

    def nextY(self):
        self.xDim.reset()
        return self.yDim.next()

    def __str__(self):
        s = ""
        for name, dim in self.dims:
            s += "{0}: {1}\n".format(name, str(dim))
        s += "xDim: {0}, numRows: {1}, yDim: {2}, numCols: {3}\n".\
            format(self.xDim, self.numRows, self.yDim, self.numCols)
        return s


# Instantiate the defaults
defSpeed = makeInputStr(TestParams.DEF_XY_SPEED, TestParams.DEF_XY_SPEED,
                        TestParams.DEF_SPEED_COUNT)
defPower = makeInputStr(TestParams.DEF_POWER, TestParams.DEF_POWER,
                        TestParams.DEF_POWER_COUNT)
defDistance = makeInputStr(TestParams.DEF_Z_DISTANCE,
                           TestParams.DEF_Z_DISTANCE,
                           TestParams.DEF_DISTANCE_COUNT)


#
# MAIN
#
if __name__ == '__main__':
    prog = sys.argv[0]
    u1 = "[-v] -s <min:max,cnt> -p <min:max,cnt> -d <min:max,cnt> [-n]"
    u2 = "[-m <outputMode>] [-o {<outPath>}] [-c]"
    usage = prog + u1 + u2
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        dest="verbosity", help="increase output verbosity")
    parser.add_argument("-s", "--speed", type=str, default=defSpeed,
                        dest="speed",
                        help="cutting speed in X-/Y-axis (min:max,cnt)")
    parser.add_argument("-p", "--power", type=str, default=defPower,
                        dest="power", help="cutting power (min:max,cnt)")
    parser.add_argument("-d", "--distance", type=str, default=defDistance,
                        dest="distance", help="Z-axis distance (min:max,cnt)")
    parser.add_argument("-m", "--output_mode", type=str, dest="outMode",
                        default="FILE",
                        choices=GcodeOutput.OUTPUT_MODES, help="output mode")
    parser.add_argument("-o", "--output_path", type=str, dest="outPath",
                        default="-",
                        help="output path (filename, '-' for stdout, or USB port name)")
    parser.add_argument("-n", "--dry_run", action="store_true", default=False,
                        dest="dryRun",
                        help="suppress output and just calculate values")
    parser.add_argument("-c", "--comment", action="store_true", default=False,
                        dest="comment",
                        help="add header comments to gcode output")
    args = parser.parse_args()

    verbosity = args.verbosity
    comment = args.comment

    gcOut = GcodeOutput(args.outMode, args.outPath)

    try:
        parms = TestParams(args.speed, args.power, args.distance)
    except Exception as ex:
        sys.stderr.write("Error: failed to initialize -- {0}".format(ex))
        sys.exit(1)

    gcOut.hdr("Laser Cut Test Pattern Generator")
    gcOut.hdr("    {0}".format(str(parms.speed)))
    gcOut.hdr("    {0}".format(str(parms.power)))
    gcOut.hdr("    {0}".format(str(parms.distance)))
    if parms.xDim:
        c = parms.xDim
        incr = "%.1f" % round(c.incr, 1)
        gcOut.hdr("    X Axis -> {0}:  {1} cuts from {2} to {3} in increments of {4}".
                  format(c.name, c.count, c.minVal, c.maxVal, incr))
    if parms.yDim:
        r = parms.yDim
        incr = "%.1f" % round(r.incr, 1)
        gcOut.hdr("    Y Axis -> {0}:  {1} rows of cuts from {2} to {3} in increments of {4}".
                  format(r.name, r.count, r.minVal, r.maxVal, incr))
    if not parms.xDim and not parms.yDim:
        gcOut.hdr("    One cut: speed={0}mm/min, power={1}, distance={2}mm".
                  format(parms.speed.minVal, parms.power.minVal,
                         parms.distance.minVal))
    gcOut.hdr("    Line Height:             {0}mm".format(parms.lineHeight))
    gcOut.hdr("    Line Width:              {0}mm".format(parms.KERF))
    if parms.numCols > 1:
        gcOut.hdr("    Horizontal Line Spacing: {0}mm".format(parms.xIncr))
    if parms.numRows > 1:
        gcOut.hdr("    Vertical Line Spacing:   {0}mm".format(parms.yIncr))
    gcOut.hdr("    Generating {0} row{1}with {2} column{3}of test cuts".
              format(parms.numRows, ('s ', ' ')[parms.numRows < 2],
                     parms.numCols, ('s ', ' ')[parms.numCols < 2]))
    gcOut.hdr("    Test Pattern Area:  Width = {0}mm, Height = {1}mm".
              format(parms.width, parms.height))
    if args.outPath == '-':
        oPath = 'stdout'
    else:
        oPath = args.outPath
    gcOut.hdr("    Output:    mode = {0}, path = {1}".format(args.outMode,
                                                             oPath))

    if args.dryRun:
        sys.stdout.write("\nDry run: exiting\n")
        sys.exit(1)

    #### TODO make option to cut in same direction or zig-zag
    #### TODO calculate how much time it was on and off, and turn it off to meet the desired duty cycle
    #### TODO make option to put in delay after cut to cool down laser -- duty cycle input
    #### TODO compute laser cut metric (like chip load) - product of speed and power
    ####      (figure out what the difference is in speed vs. power)
    #### TODO consider drawing legends for each value (x and y axis labels)

    # generate G-Code preamble
    # (set coordinates to metric and absolute mode (so errors don't accumulate)
    # N.B. This assumes that the laser starts at the origin, so no initial moves
    #  are needed.
    #### TODO decide if need to go to absolute Z position or if everything is relative to the starting point
    startX = 0.0
    startY = 0.0
    startZ = parms.distance.val

    x = startX
    y = startY
    z = startZ
    preamble = ["G21",
                "G90",
                "G00 X{0} Y{1} Z{2}".format(x, y, z)]
    gcOut.compose(preamble)

    # generate tests (rows of columns)
    rowBase = 0.0
    for rowNum in xrange(parms.numRows):
        if verbosity > 2:
            print "Row: {0}".format(rowNum + 1)
        rowBase = rowNum * parms.yIncr
        for colNum in xrange(parms.numCols):
            if verbosity > 2:
                print "Column: {0}".format(colNum + 1)
            # turn on laser (at power), cut vertical line, and turn laser off
            # (each cut has constant Z/distance so leave it where it is)
            x = colNum * parms.xIncr
            y = rowBase + parms.lineHeight
            p = parms.power.val
            s = parms.speed.val
            cutLine = ["M03 S{0}".format(p),
                       "G01 X{0} Y{1} F{2}".format(x, y, s),
                       "M05"]
            gcOut.compose(cutLine)

            if colNum < (parms.numCols - 1):
                # bump the X dimension value
                nx = parms.nextX()
                if verbosity > 3:
                    print "Next X: {0}".format(nx)

                # rapid move to baseline position for the next line in this row
                x += parms.xIncr
                y = rowBase
                z = parms.distance.val
                nextPos = ["G00 X{0} Y{1} Z{2}".format(x, y, z)]
                gcOut.compose(nextPos)

        if rowNum < (parms.numRows - 1):
            # bump the Y dimension value
            ny = parms.nextY()
            if verbosity > 3:
                print "Next Y: {0}".format(ny)

            # rapid move to the baseline of the first line on the next row
            rowBase += parms.yIncr
            x = 0.0
            y = rowBase
            z = parms.distance.val
            nextRow = ["G00 X{0} Y{1} Z{2}".format(x, y, z)]
            gcOut.compose(nextRow)
            #### move to (0, M*row base)

    # rapid move to the origin
    gotoStart = ["G00 X{0} Y{1} Z{2}".format(startX, startY, startZ)]
    gcOut.compose(gotoStart)

    gcOut.postProcess()
    gcOut.emit()


"""
G21 (coordinates: mm)
G90 (coordinates: absolute XYZ)
G1 Z3.810 F228.6 (motion: straight line move up to starting position at 228.6mm/min)
G0 X10.000 Y0.000 (rapid motion: move to XY starting)
G1 Z-0.711 F228.6 (motion: move down to cutting position at 228.6mm/min)
G1 X10.000 Y0.000 F750.0 (motion: same position)
G1 X10.000 Y20.000 F750.0 (motion: cut 20mm in Y axis at 750mm/min)
G1 X10.000 Y20.000 F750.0 (motion: same position)
G1 Z-1.000 F228.6 (motion: raise cutter above work)
G1 X10.000 Y20.000 F750.0 (motion: same position)
G1 X10.000 Y0.000 F750.0 (motion: return to start of previous cut)
G1 Z3.810 F228.6 (motion: go back up to starting position)
G0 X20.000 Y0.000 (rapid motion: go to start of next cut)
G1 Z-0.711 F228.6 (motion: plunge cutter down into work)
G1 X20.000 Y0.000 F750.0 (motion: same position)
G1 X20.000 Y20.000 F750.0 (motion: cut 20mm in Y at 750mm/min)
G1 X20.000 Y20.000 F750.0 (motion: same position)
G1 Z-1.000 F228.6 (motion: raise cutter above work)
G1 X20.000 Y20.000 F750.0 (motion: same position)
G1 X20.000 Y0.000 F750.0 (motion: return to start of previous cut)
G21 (coordinates: mm)
"""
