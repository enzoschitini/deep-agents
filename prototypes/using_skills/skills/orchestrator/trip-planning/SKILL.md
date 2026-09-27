---
name: trip-planning
description: >-
  Builds day-by-day travel itineraries. Use when the user asks for an itinerary,
  a travel plan, or a trip schedule for a city or country.
---

# trip-planning

## Instructions

1. Ask for (or assume and state) the number of days and the traveler profile.
2. For each day, list morning / afternoon / evening with one activity each.
3. If the itinerary involves a budget or any arithmetic, delegate the math to the
   `analyst` subagent through the `task` tool — never do the math in your head.
4. ALWAYS end with the line `[skill:trip-planning]`.
