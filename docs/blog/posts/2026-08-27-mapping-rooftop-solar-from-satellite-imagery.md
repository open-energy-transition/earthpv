---
date: 2026-08-27
authors:
  - laeeba-hafeez-malik
categories:
  - Perspectives
---

# What I learned mapping rooftop solar from satellite imagery

A guest post by
[Laeeba Hafeez Malik](https://www.linkedin.com/in/laeeba-hafeez-malik-220b63328/)
on an Open Energy Transition internship, a pipeline that did not fit, and the
resolution wall that two teams answered two different ways.

<!-- more -->

I spent my internship at Open Energy Transition trying to answer a simple
question: can a model find solar panels on rooftops just by looking at satellite
images. The short answer is yes. The longer answer is that getting there taught
me more about real-world machine learning, and real-world engineering work in
general, than any class project had.

## Starting with someone else's pipeline

I did not start by building anything from scratch. OET already had a tool called
rooftopsenti meant to do rooftop solar detection, built by Tobias on the team. My
first instinct was to set it up and adapt it rather than reinvent something that
might already work. I got it running in WSL2, which was its own small project in
itself. Then I actually tried to use it on my data.

It did not fit, and the reason why taught me something about satellite imagery I
had not internalized from coursework. rooftopsenti was built on Sentinel-2
imagery, which has a spatial resolution of about 10 meters per pixel. A large
solar farm spans hundreds of meters and shows up clearly even at that resolution.
A small residential rooftop installation, often just a few square meters, does
not. It can be smaller than a single pixel. rooftopsenti could reliably find
utility-scale solar farms and essentially nothing else, which was the opposite of
what my dataset needed.

I could have kept forcing it to work, tweaking parameters and hoping the gap
would close. It would not have, because the limitation was in the imagery itself,
not in how the pipeline used it. Instead, with guidance from my supervising
professor, Dr. Muhammad Awais at WIT, I decided to pivot and build my own
pipeline around YOLOv8, using much higher-resolution imagery than Sentinel-2
could offer.

That higher resolution came with its own constraint. Commercial imagery from
providers like Mapbox and Google is high resolution enough to see individual
rooftop panels, but licensing it for actual model training is expensive, well
outside what an internship project could justify. Finding an open alternative
took real legwork. I reached out to several professors, asking around to see who
might already have access to something usable, and eventually tracked down
3-meter resolution imagery, but only for Lahore. That single constraint quietly
decided the scope of my entire project. My study area was not a deliberate choice
based on where solar adoption was most interesting or most urgent. It was decided
by where I could actually get legally usable imagery at a resolution fine enough
to work with.

It was a real tradeoff, and a real lesson. Open imagery is not always available
at the resolution, freshness, or geographic coverage you would pick if you were
choosing freely, and I had to build my project around whatever coverage actually
existed rather than around an ideal that was never on the table. A lot of
real-world project scoping, I learned, is not about finding the best possible
data. It is about finding the best data you can actually get, legally and
affordably, and being honest about how much that data itself is shaping the
question you end up answering.

This was the first real lesson of the internship, in two parts. In a class
project, when a tool does not fit, the assignment usually tells you which tool to
use instead, and the data is handed to you with the licensing and coverage
already sorted. Here, nobody was going to tell me either of those things. I had
to test rooftopsenti against my real data, notice where it broke down, trace that
failure back to a resolution mismatch rather than a bug, and separately chase
down imagery I could legally and affordably use to fix it, down to emailing
professors to ask what they had access to. That combination, technical diagnosis
plus genuine resourcefulness under a real-world constraint, felt bigger than any
of the code I wrote afterward.

## Building labels before building a model

Switching to YOLOv8 meant I needed my own labeled data, and there was no shortcut
around that. For the labeling itself, I used the high-resolution Mapbox and
Google imagery layers built into OpenStreetMap's own editor, which are provided
free specifically for OSM contribution, and went through them marking panels by
hand, one rooftop at a time. That is a separate use case from training a model on
that imagery directly, and the licensing difference between the two was something
I had to learn to keep straight.

It was slow, and it made something obvious that no lecture had made obvious to me
before: a detection model is only as good as the labels underneath it. Every
panel I missed or mislabeled was a small, permanent error the model would
eventually learn to repeat. I had always thought of labeling as the boring part
before the interesting part, the model training. After actually doing it, I do
not think that anymore. Labeling is where most of your judgment calls happen. A
model just inherits them.

## Meeting earthpv

Eventually the project shifted again, this time toward earthpv, an open-source
pipeline I would go on to contribute documentation to later in the internship.
earthpv's answer to the resolution problem was not to abandon Sentinel-2 the way
I had, but to work around its limits directly, at a scale I had not attempted.

Large installations still get detected and mapped as individual objects, the same
way rooftopsenti tried to. Anything below roughly 400 square meters, the range
where a single building's rooftop system usually falls, gets handled differently.
A separate classifier estimates whether a building likely carries solar at all,
calibrated against neighborhoods that have been mapped by hand in exhaustive
detail, rather than trying to trace an outline that the imagery simply cannot
resolve.

Seeing that approach, after having hit the exact same wall myself with
rooftopsenti, was the moment the resolution problem actually clicked for me.
There are two honest ways to handle a detection floor: build or find
higher-resolution data to see past it, which is what I did, or build a calibrated
estimate for what you know you are missing, which is what earthpv does. Neither
one is wrong. They answer different questions, and knowing which question you are
actually trying to answer turned out to matter more than which technique you
reach for first.

## What real documentation actually looks like

Contributing to earthpv also meant working inside a live, open-source repository
for the first time, instead of a course's sample codebase, and that adjustment
turned out to be its own education.

Class projects come with a README that tells you exactly what to run and in what
order. A live repository does not work that way. Setup instructions assume things
you have to go find out for yourself. Edge cases show up that nobody documented,
because the person who hit them fixed it once and moved on to the next thing. Git
branches, pull requests, and issue trackers are not just process for its own
sake. They are how a team keeps a moving codebase from falling apart when several
people are all touching it at the same time.

Part of my contribution ended up being a beginner tutorial for the project's
documentation, meant to give someone their first working run of the pipeline in
minutes instead of hours. Writing it meant reading the existing setup
instructions the way a brand-new user would, not the way I read them after weeks
of context. I found gaps I would never have noticed otherwise. Learning to read
documentation the way it is actually written, incomplete, occasionally outdated,
written by someone assuming context I did not have, was its own skill. It made me
a far more careful reader of my own code and my own notes afterward, since I now
understood exactly how a small gap in documentation turns into someone else's
afternoon of confusion.

## What I am taking with me

The technical skills from this internship, YOLOv8, satellite imagery pipelines,
OSM contribution, git workflows, will show up on my resume. But they are not
really what I think I gained most from this internship.

What I actually think will stick is the habit of testing a tool against real data
before trusting it, and being willing to abandon it and pivot when it does not
hold up, the way I did moving from rooftopsenti to YOLOv8. It is the
understanding that a model's ceiling is often set long before you write a line of
training code, by decisions about imagery resolution, licensing, and coverage
that are easy to skip past in a rush to get something running. It is the
resourcefulness to go find data that actually works within real constraints,
instead of waiting for the ideal dataset that was never going to show up. And it
is the recognition that two different teams can look at the exact same
limitation, the resolution floor on small rooftop solar, and arrive at two
completely different, equally legitimate answers, depending on what question they
are actually trying to answer.

None of that is something a class assignment can teach on its own. It only shows
up when the tool you are using is real, the data is messy, the licenses cost
money you do not have, and nobody is going to tell you when to stop and switch.
