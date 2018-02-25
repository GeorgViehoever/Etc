Software that I used during the 2017 solar eclipse. Result on https://www.youtube.com/watch?v=za5jLJQ14ds .
I used a Raspberry Pi to control a RaspberryPi running INDI controlling a Canon EOS 80D. 
The software published here does not include the INDI open software, just the parts that I wrote myself.
Also missing is decent install documentation. But maybe you find this stuff nevertheless useful.

start.sh: script to start/stop INDI as a system service
piRaw.py: python script to do 10 second "RAW" exposures. Not really RAW, but close. Needs several seconds for a single shot. 
          Result here https://www.youtube.com/watch?v=4ZNek8Q8Nys
indiEclipse.py: Controller than runs the sequence of photos during the eclipse.
eclipseAlign.py: Script to align the eclipse photos, to run on PC. Uses hough transform to find center of sun.
          Did 95% of the work to get the pictures for https://www.youtube.com/watch?v=za5jLJQ14ds aligned to
          a central position.
99-canon_indi.rules: Config file for raspi to correctly identify the type of device. Did have some issues without this.

License:
Use as you like. I claim no rights to this software. If you like it, consider to send me a chocolate.

Georg Viehoever

