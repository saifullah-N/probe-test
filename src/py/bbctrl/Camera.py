#!/usr/bin/env python3
################################################################################
#                                                                              #
#                This file is part of the Buildbotics firmware.                #
#                                                                              #
#                  Copyright (c) 2015 - 2018, Buildbotics LLC                  #
#                             All rights reserved.                             #
#                                                                              #
#     This file ("the software") is free software: you can redistribute it     #
#     and/or modify it under the terms of the GNU General Public License,      #
#      version 2 as published by the Free Software Foundation. You should      #
#      have received a copy of the GNU General Public License, version 2       #
#     along with the software. If not, see <http://www.gnu.org/licenses/>.     #
#                                                                              #
#     The software is distributed in the hope that it will be useful, but      #
#          WITHOUT ANY WARRANTY; without even the implied warranty of          #
#      MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU       #
#               Lesser General Public License for more details.                #
#                                                                              #
#       You should have received a copy of the GNU Lesser General Public       #
#                License along with the software.  If not, see                 #
#                       <http://www.gnu.org/icenses/>.                         #
#                                                                              #
#                For information regarding this software email:                #
#                  "Joseph Coffland" <joseph@buildbotics.com>                  #
#                                                                              #
################################################################################

import os
import fcntl
import select
import struct
import mmap
import pyudev
import base64
import socket
import ctypes
from tornado import gen, web, iostream
import bbctrl

try:
    import v4l2
except:
    import bbctrl.v4l2 as v4l2


def array_to_string(a):
    def until_zero(a):
        for c in a:
            if c == 0: return
            yield c

    return ''.join([chr(i) for i in until_zero(a)])


def fourcc_to_string(i):
    return \
        chr((i >>  0) & 0xff) + \
        chr((i >>  8) & 0xff) + \
        chr((i >> 16) & 0xff) + \
        chr((i >> 24) & 0xff)


def string_to_fourcc(s): return v4l2.v4l2_fourcc(s[0], s[1], s[2], s[3])


def format_frame(frame):
    frame = [b'--', VideoHandler.boundary.encode('utf8'), b'\r\n',
             b'Content-type: image/jpeg\r\n',
             b'Content-length: %d\r\n\r\n' % len(frame), frame]
    return b''.join(frame)


def get_image_resource(path):
    path = bbctrl.get_resource(path)

    with open(path, 'rb') as f:
        return format_frame(f.read())


class VideoDevice(object):
    def __init__(self, path = '/dev/video0'):
        self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
        self.buffers = []


    def fileno(self): return self.fd


    def get_audio(self):
        b = v4l2.v4l2_audio()
        b.index = 0

        l = []

        while True:
            try:
                fcntl.ioctl(self, v4l2.VIDIOC_ENUMAUDIO, b)
                l.append((array_to_string(b.name), b.capability, b.mode))
                b.index += 1

            except OSError: break

        return l


    def get_formats(self):
        b = v4l2.v4l2_fmtdesc()
        b.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
        b.index = 0

        l = []

        while True:
            try:
                fcntl.ioctl(self, v4l2.VIDIOC_ENUM_FMT, b)

                l.append((fourcc_to_string(b.pixelformat),
                          array_to_string(b.description)))

                b.index += 1

            except OSError: break

        return l


    def get_frame_sizes(self, fourcc):
        b = v4l2.v4l2_frmsizeenum()
        b.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
        b.pixel_format = fourcc

        sizes = []

        while True:
            try:
                fcntl.ioctl(self, v4l2.VIDIOC_ENUM_FRAMESIZES, b)

                if b.type == v4l2.V4L2_FRMSIZE_TYPE_DISCRETE:
                    sizes.append((b.discrete.width, b.discrete.height))

                else:
                    sizes.append((b.stepwise.min_width, b.stepwise.max_width,
                                  b.stepwise.step_width, b.stepwise.min_height,
                                  b.stepwise.max_height,
                                  b.stepwise.step_height))

                b.index += 1 # pylint: disable=no-member

            except OSError: break

        return sizes


    def set_format(self, width, height, fourcc):
        fmt = v4l2.v4l2_format()
        fmt.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
        fcntl.ioctl(self, v4l2.VIDIOC_G_FMT, fmt)

        fmt.fmt.pix.width = width
        fmt.fmt.pix.height = height
        fmt.fmt.pix.pixelformat = fourcc

        fcntl.ioctl(self, v4l2.VIDIOC_S_FMT, fmt)


    def create_buffers(self, count):
        # Create buffers
        rbuf = v4l2.v4l2_requestbuffers()
        rbuf.count = count;
        rbuf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE;
        rbuf.memory = v4l2.V4L2_MEMORY_MMAP;

        fcntl.ioctl(self, v4l2.VIDIOC_REQBUFS, rbuf)

        for i in range(rbuf.count):
            # Get buffer
            buf = v4l2.v4l2_buffer()
            buf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
            buf.memory = v4l2.V4L2_MEMORY_MMAP
            buf.index = i
            fcntl.ioctl(self, v4l2.VIDIOC_QUERYBUF, buf)

            # Mem map buffer
            mm = mmap.mmap(self.fileno(), buf.length, mmap.MAP_SHARED,
                           mmap.PROT_READ | mmap.PROT_WRITE,
                           offset = buf.m.offset)
            self.buffers.append(mm)

            # Queue the buffer for capture
            fcntl.ioctl(self, v4l2.VIDIOC_QBUF, buf)


    def _dqbuf(self):
        buf = v4l2.v4l2_buffer()
        buf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
        buf.memory = v4l2.V4L2_MEMORY_MMAP
        fcntl.ioctl(self, v4l2.VIDIOC_DQBUF, buf)

        return buf


    def _qbuf(self, buf):
        fcntl.ioctl(self, v4l2.VIDIOC_QBUF, buf)


    def read_frame(self):
        buf = self._dqbuf()
        mm = self.buffers[buf.index]

        frame = mm.read(buf.bytesused)
        mm.seek(0)
        self._qbuf(buf)

        return frame


    def flush_frame(self): self._qbuf(self._dqbuf())


    def get_info(self):
        caps = v4l2.v4l2_capability()
        fcntl.ioctl(self, v4l2.VIDIOC_QUERYCAP, caps)

        caps._driver   = array_to_string(caps.driver)
        caps._card     = array_to_string(caps.card)
        caps._bus_info = array_to_string(caps.bus_info)

        l = []
        c = caps.capabilities
        if c & v4l2.V4L2_CAP_VIDEO_CAPTURE: l.append('video_capture')
        if c & v4l2.V4L2_CAP_VIDEO_OUTPUT: l.append('video_output')
        if c & v4l2.V4L2_CAP_VIDEO_OVERLAY: l.append('video_overlay')
        if c & v4l2.V4L2_CAP_VBI_CAPTURE: l.append('vbi_capture')
        if c & v4l2.V4L2_CAP_VBI_OUTPUT: l.append('vbi_output')
        if c & v4l2.V4L2_CAP_SLICED_VBI_CAPTURE: l.append('sliced_vbi_capture')
        if c & v4l2.V4L2_CAP_SLICED_VBI_OUTPUT: l.append('sliced_vbi_output')
        if c & v4l2.V4L2_CAP_RDS_CAPTURE: l.append('rds_capture')
        if c & v4l2.V4L2_CAP_VIDEO_OUTPUT_OVERLAY:
            l.append('video_output_overlay')
        if c & v4l2.V4L2_CAP_HW_FREQ_SEEK: l.append('hw_freq_seek')
        if c & v4l2.V4L2_CAP_RDS_OUTPUT: l.append('rds_output')
        if c & v4l2.V4L2_CAP_TUNER: l.append('tuner')
        if c & v4l2.V4L2_CAP_AUDIO: l.append('audio')
        if c & v4l2.V4L2_CAP_RADIO: l.append('radio')
        if c & v4l2.V4L2_CAP_MODULATOR: l.append('modulator')
        if c & v4l2.V4L2_CAP_READWRITE: l.append('readwrite')
        if c & v4l2.V4L2_CAP_ASYNCIO: l.append('asyncio')
        if c & v4l2.V4L2_CAP_STREAMING: l.append('streaming')
        caps._caps = l

        return caps


    def set_fps(self, fps):
        setfps = v4l2.v4l2_streamparm()
        setfps.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE;
        setfps.parm.capture.timeperframe.numerator = 1
        setfps.parm.capture.timeperframe.denominator = fps
        fcntl.ioctl(self, v4l2.VIDIOC_S_PARM, setfps)


    def start(self):
        buf_type = v4l2.v4l2_buf_type(v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE)
        fcntl.ioctl(self, v4l2.VIDIOC_STREAMON, buf_type)


    def stop(self):
        buf_type = v4l2.v4l2_buf_type(v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE)
        fcntl.ioctl(self, v4l2.VIDIOC_STREAMOFF, buf_type)


    def close(self):
        if self.fd is None: return
        try:
            os.close(self.fd)
        finally: self.fd = None


class Camera(object):
    def __init__(self, ioloop, args, log):
        self.ioloop = ioloop
        self.log = log.get('Camera')

        self.width = args.width
        self.height = args.height
        self.fps = args.fps
        self.fourcc = 'MJPG'
        self.max_clients = args.camera_clients

        self.overtemp = False
        self.dev = None
        self.clients = []
        self.path = None
        self.have_camera = False

        # Find connected cameras
        for i in range(4):
            path = '/dev/video%d' % i
            if os.path.exists(path):
                self.have_camera = True
                self.open(path)
                break

        # Get notifications of camera (un)plug events
        self.udevCtx = pyudev.Context()
        self.udevMon = pyudev.Monitor.from_netlink(self.udevCtx)
        self.udevMon.filter_by(subsystem = 'video4linux')
        ioloop.add_handler(self.udevMon, self._udev_handler, ioloop.READ)
        self.udevMon.start()


    def _udev_handler(self, fd, events):
        action, device = self.udevMon.receive_device()
        if device is None or self.dev is not None: return

        path = str(device.device_node)

        if action == 'add':
            self.have_camera = True
            self.open(path)

        if action == 'remove' and path == self.path:
            self.have_camera = False
            self.close()


    def _send_frame(self, frame):
        if not len(self.clients): return

        try:
            frame = format_frame(frame)
            for i in range(self.max_clients):
                if i < len(self.clients):
                    self.clients[-(i + 1)].write_frame(frame)

        except Exception as e:
            self.log.warning('Failed to write frame to client: %s' % e)


    def _fd_handler(self, fd, events):
        try:
            if len(self.clients):
                frame = self.dev.read_frame()
                self._send_frame(frame)

            else: self.dev.flush_frame()

        except Exception as e:
            if isinstance(e, BlockingIOError): return

            self.log.warning('Failed to read from camera.')
            self.ioloop.remove_handler(fd)
            self.close()


    def _update_client_image(self):
        if self.have_camera and not self.overtemp: return
        if self.overtemp and self.have_camera: img = 'overtemp'
        else: img = 'offline'

        if len(self.clients): self.clients[-1].write_img(img)


    def open(self, path):
        try:
            self._update_client_image()
            self.path = path
            if self.overtemp: return
            self.dev = VideoDevice(path)

            caps = self.dev.get_info()
            self.log.info('%s, %s, %s, %s', caps._driver, caps._card,
                          caps._bus_info, caps._caps)

            if caps.capabilities & v4l2.V4L2_CAP_VIDEO_CAPTURE == 0:
                raise Exception('Video capture not supported.')

            fourcc  = string_to_fourcc(self.fourcc)
            formats = self.dev.get_formats()
            sizes   = self.dev.get_frame_sizes(fourcc)

            self.log.info('Formats: %s', formats)
            self.log.info('Sizes: %s', sizes)
            self.log.info('Audio: %s', self.dev.get_audio())

            hasFormat = False
            for name, description in formats:
                if name == self.fourcc: hasFormat = True

            if not hasFormat:
                raise Exception(self.fourcc + ' video format not supported.')

            self.dev.set_format(self.width, self.height, fourcc = fourcc)
            self.dev.set_fps(self.fps)
            self.dev.create_buffers(4)
            self.dev.start()

            self.ioloop.add_handler(self.dev, self._fd_handler,
                                    self.ioloop.READ)

            self.log.info('Opened camera ' + path)


        except Exception as e:
            self.log.warning('While loading camera: %s' % e)
            self._close_dev()


    def _close_dev(self):
        if self.dev is None: return
        try:
            self.dev.close()
        except Exception as e: self.log.warning('While closing camera: %s', e)

        self.dev = None


    def close(self, overtemp = False):
        self._update_client_image()
        if self.dev is None: return

        try:
            self.ioloop.remove_handler(self.dev)
            try:
                self.dev.stop()
            except: pass

            self._close_dev()
            self.log.info('Closed camera')

        except: self.log.exception('Exception while closing camera')
        finally: self.dev = None


    def add_client(self, client):
        self.log.info('Adding camera client: %d' % len(self.clients))

        if self.max_clients <= len(self.clients):
            self.clients[-self.max_clients].write_img('in-use')

        self.clients.append(client)
        self._update_client_image()


    def remove_client(self, client):
        self.log.info('Removing camera client')
        try:
            self.clients.remove(client)
        except: pass


    def set_overtemp(self, overtemp):
        if self.overtemp == overtemp: return
        self.overtemp = overtemp

        if overtemp: self.close(True)
        elif self.path is not None: self.open(self.path)



class VideoHandler(web.RequestHandler):
    boundary = '-f36a3a39e5c955484390e0e3a6b031d1---'


    def __init__(self, app, request, **kwargs):
        super().__init__(app, request, **kwargs)
        self.camera = app.camera


    @web.asynchronous
    def get(self):
        self.request.connection.stream.max_write_buffer_size = 10000

        self.set_header('Cache-Control', 'no-store, no-cache, must-revalidate, '
                        'pre-check=0, post-check=0, max-age=0')
        self.set_header('Connection', 'close')
        self.set_header('Content-Type', 'multipart/x-mixed-replace;boundary=' +
                        self.boundary)
        self.set_header('Expires', 'Mon, 3 Jan 2000 12:34:56 GMT')
        self.set_header('Pragma', 'no-cache')

        if self.camera is None: self.write_img('offline')
        else: self.camera.add_client(self)


    def write_img(self, name):
        self.write_frame_twice(get_image_resource('http/images/%s.jpg' % name))


    def write_frame(self, frame):
        # Don't allow too many frames to queue up
        min_size = len(frame) * 2
        if self.request.connection.stream.max_write_buffer_size < min_size:
            self.request.connection.stream.max_write_buffer_size = min_size

        try:
            self.write(frame)
            self.flush()

        except iostream.StreamBufferFullError:
            pass # Drop frame if buffer is full


    def write_frame_twice(self, frame):
        self.write_frame(frame)
        self.write_frame(frame)


    def on_connection_close(self): self.camera.remove_client(self)
