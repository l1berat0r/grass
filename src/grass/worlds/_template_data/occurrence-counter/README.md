# Occurrence Counter

This is an occurrence-only GRASS WorldPackage starter. It begins with a world-scoped
integer `counter` set to `0`. At logical time `10`, the scenario rule executes the
referenced GEL program and commits the resulting value `1` through the normal runtime,
WorldEffect validation, and Event transition path.

The directory is an ordinary editable WorldPackage. `package.json` references
`world.json`, and `world.json` references `mechanics/increment.gel`. It uses no hidden
template mechanics, actor behavior, provider configuration, or privileged Event path.

Typical workflow:

```text
grass world validate .
grass run create .
grass run advance RUN
grass inspect state RUN
grass inspect events RUN
grass run verify RUN
```
