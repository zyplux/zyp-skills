# Change Skeleton

Consider having just two sections: `functional requirements`, `tech requirements`. And inside each you have requirements ordered by confidence levels 0-100%.
User initial idea gets converted into requirements (many-to-many, but most of the time fan-out), that land into one of two sections: FR or TR (or both), then assigned a confidence level, depending on how clear the requirement is.
Everything below 100% confidence should have a question in it (known part and unknown part)
As user provides responses, as per usual interaction process, new requirements appear, existing get updated, some can disapper (100% requirement can go away if a pivot happened).
With this system it's easy to estimate plan readiness precisely (100% reqs/total reqs) and the progress.
The system is also more straight forward and simple.
> Remember - one of the most essential goal of the process is to let the agent dig into user's brain to capture the idea in full. To not have a situation where user expected something as a common sense, but never wrote it down.
> Other goal is of course collaboration.
