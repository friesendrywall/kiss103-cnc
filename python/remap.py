from interpreter import *
import traceback
import m500_fid as _m500
import m510_fid as _m510
import m520_fid as _m520


def m500_fid(self, **words):
    try:
        return _m500.m500_fid(self, **words)
    except Exception:
        traceback.print_exc()
        return INTERP_ERROR


def m510_fid(self, **words):
    try:
        return _m510.m510_fid(self, **words)
    except Exception:
        traceback.print_exc()
        return INTERP_ERROR


def m520_fid(self, **words):
    try:
        return _m520.m520_fid(self, **words)
    except Exception:
        traceback.print_exc()
        return INTERP_ERROR
