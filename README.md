# Operation Crucible

The purpose of Operation Crucible is automation. I have been what one of my professors calls "dumb lazy" by trying to manually do all my coursework and by extension put off any automation of said coursework. Now, I will be "smart lazy" by designing a framework that does the repetitive part of my coursework. More specifically, what I am attempting to do is create an Ansible framework that auto-designs virtual machine networks and runs simulated traffic and more, based off of minimal user input. The goal? For my manual input per assignment to be measured in mere minutes, rather than hours, while still gaining the valuable experience provided by said coursework.

## Setup & Requirements

For starters go to images/iso and read instructions there, youll have to populate that folder once you've downoladed this repo to your local filesystem. Wouldn't reccomend trying this out at the moment as it's temporarily hard coded to me while in the proof of concept phase. Very soon I am going to do my best to make this usable with minimal modifcation.

## Log

Notable Versions:<br>
&emsp;Version 0.1:<br>
&emsp;&emsp;Description: Create a fresh linux Virtual Machine installation, and with no user input achieve ansible.builtin.ping = pong<br>
&emsp;&emsp;Status: Complete!<br>
&emsp;Version 0.2:<br>
&emsp;&emsp;Description: Create a fresh windows Virtual Machine installation, and with no user input achieve ansible.builtin.ping = pong<br>
&emsp;&emsp;Status: Incomplete<br>
