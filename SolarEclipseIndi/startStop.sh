#!/bin/bash
if [ "$#" -ne 1 ]; then
    echo "Usage: $0 start|stop"
    exit 1
fi
if [ "$1" == "start" ]; then
    echo "$(date) start">>/home/pi/IndiFIFO/log.txt
    echo "start indi_canon_ccd -v"> /home/pi/IndiFIFO/myFIFO
elif [ "$1" == "stop" ]; then
    echo "$(date) stop">>/home/pi/IndiFIFO/log.txt
    echo "stop indi_canon_ccd -v"> /home/pi/IndiFIFO/myFIFO
else
    echo "Unknown command"
    exit 1
fi
