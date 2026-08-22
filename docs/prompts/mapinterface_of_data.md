# Map Interface of Data
We want a simple web page to communicate to the public about h2s level and
what may be happening.

We need a backgound map of the area, the Tijuana River Valley, San Ysidro, and Imperal beach

# user interface library
What is the best user interface library for this?

# Static Map:
We want to show the current level of the h2s. That data will come from s3.
We want to show the current temparature and humidity. That data will come from s3.
We want to show the current wind speed and direction, in a  dynamic manner as wind verctors. That data will come from s3.
We want to show the current effluent flow from the south bay water treatment plant. That data will come from s3.
We want to show the present ocean prediction model. That data will come from s3.

#  Dynamic mapping:
Initially, we will want to show the last 7 days in a dynmaic manner.
I want to show wind speed and direction as vectors.
We want to show a plot of the h2s levels over the week as the time slider.
We want to show the level of effluent flow as color coding the channels, from the plant to the saturn bridge in the northern channel.
and from the plant down the main channel to the saturn street crossing.

# Long Term Dynamic mapping:
We want to show the number of hours that the h2s levels are over 5 ppb and 30 ppb for an evening at Nestor.
Users can select a time window (7 day? 30 day? 90 day?) that will show the dynamic mapping.

Where do we get the weather data for the wind vectors in a user interface friendly manner?
