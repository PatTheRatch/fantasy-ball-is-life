You have already completed a forensic audit of the current FCP repository.

The Product Constitution below is now authoritative. Where your earlier inferred product vision conflicts with it, use the Product Constitution.

Now perform the architecture phase.

Assume sunk development cost is zero.

Do not start by refactoring the existing application.

First, temporarily ignore the current implementation and answer:

> If FCP did not exist today and we were starting from an empty repository with this Product Constitution, what architecture would you choose?

Design the ideal greenfield system from first principles.

Cover at minimum:

- overall system architecture
- frontend architecture
- backend/application architecture
- canonical domain model
- player identity model
- league/provider normalization
- ESPN integration boundary
- future Yahoo/Sleeper integration approach
- projection model and projection-source architecture
- user projection uploads
- projection horizons
- user projection adjustments
- shared vs private analytics
- persistence model
- historical-data model
- jobs/background processing
- authentication and authorization
- tenant isolation
- API design
- caching
- deployment
- observability
- testing strategy
- repository/file structure

Be concrete.

Show important entities, ownership boundaries, data flows, and proposed tables where useful.

Do not introduce complexity merely for theoretical scalability. Optimize for a high-quality product that could comfortably grow from one league to hundreds or thousands of users.

After completing the greenfield design, compare it against the current repository you audited.

For each major current subsystem or concept, classify it as:

KEEP  
KEEP BUT CLEAN UP  
REFACTOR  
REPLACE  
DELETE

Distinguish between preserving:

- a concept
- an algorithm
- a data model
- an implementation

For example, it is valid to recommend preserving the current draft optimization algorithm while replacing the API, persistence, and module structure around it.

Then give a decisive recommendation:

1. Continue largely as-is
2. Refactor selected areas
3. Rebuild major subsystems
4. Preserve domain logic but rebuild the application around it
5. Full greenfield restart
6. Another clearly defined approach

Do not hedge simply because both approaches are possible.

Explain which option you believe produces the best FCP given that migration effort, downtime, tokens, and previous development effort have effectively zero cost.
Save it in docs as an MD file.

Do not modify any code yet.

This phase ends with an architecture recommendation and target design, not implementation.
