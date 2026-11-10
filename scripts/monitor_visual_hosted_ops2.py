#!/usr/bin/env python3
"""Exact-UID lifecycle monitoring for the five zero-native ops2 recoveries."""
import monitor_visual_hosted_cci_v1 as monitor
import provision_visual_hosted_ops2 as deployment

def main():
 original=monitor.cycle
 def cycle(*a,**kw):
  kw['receipts']=deployment.RECEIPTS
  return original(*a,**kw)
 monitor.RECEIPTS=deployment.RECEIPTS
 monitor.app_name=deployment.app_name
 monitor.HARNESSES=deployment.CELLS
 monitor.cycle=cycle
 monitor.main()
if __name__=='__main__':main()
