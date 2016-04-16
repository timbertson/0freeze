<img src="http://gfxmonk.net/dist/status/project/0freeze.png">

# 0freeze

Creates a version-frozen copy of a zeroinstall feed (including dependencies).

The result is similar to but more portable than a selections document. A selections document
(obtained from `0install select --xml INTERFACE`) is locked to specific implementation IDs,
package names and local feed paths.

In contrast, 0freeze only locks down versions, so the generated feed can be used
cross-platform - as long as the given version is available on all required platforms.

Additionally, the level of freezing can be controlled with the --components option.

Package implementations are not version-restrcicted beyond what is already
specified in the original feed.

Local feeds are not included as dependencies (since they include system-specific path information),
but the version of the local implementation is still used. It's up to you to ensure that the
same version is available wherever you run the frozen feed.

# Known Issues:

If a published feed is modified after the frozen feed is generated, it's possible to introduce
new (unrestricted) dependencies. This is considered bad practice, but there is currently no
protection against it.
