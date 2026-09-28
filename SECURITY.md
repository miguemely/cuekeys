# Security

Please report security problems privately, using GitHub's **Report a vulnerability** button on the
repository's Security tab (private vulnerability reporting), rather than in a public issue.

Worth knowing when you assess a report:

- The host app opens outbound connections only: OSC (UDP), grandMA2 Telnet, and Companion HTTP and
  Satellite (TCP). It doesn't listen on any network port.
- grandMA2 Telnet credentials live in the layout file on the host. They're never written to the
  keypad (`config.firmware_view`), and Telnet itself isn't encrypted.
- Companion HTTP, Companion Satellite, and OSC are also plaintext protocols. Use them only on a
  trusted network or through an appropriate VPN/tunnel; CueKeys does not provide transport security.
- The host accepts keypad messages only after the firmware `hello.uid` matches the discovered USB
  serial identity. This is an identity check, not cryptographic authentication: a modified device
  with access to the same USB identity is still trusted.
- The keypad acts as a USB keyboard. Anyone who can edit its `config.json` can make it type
  keystrokes.
