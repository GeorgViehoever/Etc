#!/usr/bin/env python3
# -*- coding: utf8 -*-
""" Tool for alignment of images from solar eclipse.
Input: Directory "." with fits files
Output: aligned fits files in directory "./aligned"
"""

#
# formalia
#
__author__      = "Georg Viehoever"
__copyright__   = "(c) 2017 Georg Viehoever"
__license__   ="""
/*
* ----------------------------------------------------------------------------
* "THE CHOCOLATE LICENSE":
* Georg Viehoever wrote this file in 2017. As long as you retain this notice you
* can do whatever you want with this stuff. If we meet some day, and you think
* this stuff is worth it, you can buy me a chocolate in return.
* ----------------------------------------------------------------------------
*/
"""
__version__ = "0.1.1"
__status__ = "Prototype"

import pathlib as pl
import datetime as dt
import multiprocessing as mp
import traceback as tb

import astropy.io.fits as fits
import skimage.color as skiColor
import skimage.filters as skiFilter
import skimage.exposure as skiExposure
import skimage.transform as skiTransform

import numpy as np
import scipy.stats as spStats

import matplotlib.pyplot as plt

def centerSun(sourceData):
    """" centers sun using hough transform
    sourceData is expected to be ndarray(3,x,y) of floats
    :returns resultData: ndarray(3,x,y) with centered sun
    """
    #print("sourceData stats=",spStats.describe(sourceData,None))
    scale=1 #scale of computation, mainly for quick debugging
    binLimitPercent=99.0 #brightness quantile for binarization
    radius=1280.0/2.0
    radiusTolerance=30
    minStep=1#radiusTolerance#/20
    centerSample=7#20 #number of different centers to consider
    #targetCenterX, targetCenterY=( 2290.5,2315.0 )
    # transpose because ski expects channels as last component
    sourceData=sourceData.transpose()
    print("type(sourceData)=", type(sourceData), "sourceData.shape=", sourceData.shape)
    print("sourceData stats=",spStats.describe(sourceData,None))
    targetCenterX, targetCenterY = (sourceData.shape[1] / 2, sourceData.shape[0] / 2)  # note different coord systems
    print("targetX,Y=",targetCenterX,",",targetCenterY)
    #print("sourceData.dtype=",sourceData.dtype)
    gray=skiColor.rgb2gray(sourceData)
    gray=gray[::scale,::scale]
    print("gray.shape=",gray.shape,spStats.describe(gray,None))
    gradient=skiFilter.scharr(gray)
    print("gradient.shape=",gradient.shape,spStats.describe(gradient,None))
    limit=np.percentile(gradient,binLimitPercent)
    print("limit=",limit)
    gradientBin=gradient>limit
    print("gradientBin.shape=", gradientBin.shape, spStats.describe(gradientBin, None))
    # mean radius and how to scan for values
    radiusMean=int(radius/scale)
    radiusTol=int(radiusTolerance/scale)
    radii=list(range(radiusMean-radiusTol,radiusMean+radiusTol+1,int(minStep)))#np.round(np.linspace(radiusMean-radiusTol,radiusMean+radiusTol,radiusSteps))
    print("radii=",radii)
    print("computing houghCircles",dt.datetime.now())
    houghCircles=skiTransform.hough_circle(gradientBin,radii)
    print("houghCircles.shape=",houghCircles.shape,dt.datetime.now())
    print("computing houghCirclePeaks")
    houghCirclePeaks=skiTransform.hough_circle_peaks(houghCircles,radii,total_num_peaks=centerSample)#int((1-centerQuantile/100)*gray.size))#,normalize=False,)
    print("houghCirclePeaks.shape=",houghCirclePeaks[0].shape,houghCirclePeaks,dt.datetime.now())
    medX=np.median(houghCirclePeaks[1])*scale
    medY=np.median(houghCirclePeaks[2])*scale
    print("(medX,medY)=(",medX,medY,")")
    transform=skiTransform.SimilarityTransform(translation=(-(targetCenterX-medX),-(targetCenterY-medY)))
    resultData=skiTransform.warp(sourceData,transform,preserve_range=True)
    resultData=resultData.astype(np.float32)
    print("resultData stats=",spStats.describe(resultData,None))
    #print("resultData.dtype=",resultData.dtype)
    if False:
        # graphical debug
        #print("Gray.shape=",gray.shape)
        fig, axes = plt.subplots(1,5,squeeze=False)
        ax=axes[0,0]
        ax.imshow(skiExposure.equalize_hist(sourceData))
        ax=axes[0,1]
        ax.imshow(skiExposure.equalize_hist(gray))
        ax=axes[0,2]
        ax.imshow(skiExposure.equalize_hist(gradient))
        ax=axes[0,3]
        ax.imshow(houghCircles[int(len(radii)/2),:,:])
        ax = axes[0, 4]
        ax.imshow(skiExposure.equalize_hist(resultData))
        plt.show()
    return resultData.transpose() #back to old order

def doAlign(fitsName,resultDir):
    """align fitsName, store result in resultDir/"r_"+fitsName
    """
    print("input:",fitsName,", resultDir=",resultDir)
    resultName="r_"+fitsName.name
    resultPath=resultDir/resultName
    with fits.open(fitsName) as sourceImageHduList:
        #print("HduList=",sourceImageHduList.info())
        sourceData=sourceImageHduList[0].data
        #print("type(sourceData)=",type(sourceData),"sourceData.shape=",sourceData.shape)
        resultData=centerSun(sourceData)
        resultHduList=sourceImageHduList
        resultHduList[0].data=resultData
        resultHduList.writeto(resultPath,overwrite=True)

def doAlignFile(args):
    """unpacking version of doAlign
    """
    try:
        fitsName,resultDir=args
        doAlign(fitsName,resultDir)
    except Exception:
        tb.print_last()
        #raise
    return args

def main():
    """" does the job
    """
    dirPath=pl.Path.cwd()
    resultPath=dirPath/"aligned"
    print("dirPath=",dirPath,", resultPath=",resultPath)
    if not resultPath.exists():
        resultPath.mkdir()
    if not resultPath.is_dir():
        raise ValueError("Result path is not a directory")

    jobs = []
    for fitsName in dirPath.glob("*.fits"):
        job = (fitsName, resultPath)
        jobs.append(job)
        #break
    #print(jobs)
    if True:
        with mp.Pool(4) as pool:
            for result in pool.imap_unordered(doAlignFile,jobs,chunksize=1):
                print("completed",result)
    else:
        for job in jobs:
            doAlignFile(job)

if __name__ == "__main__":
    main()