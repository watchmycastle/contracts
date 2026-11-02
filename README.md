# contracts

Shared contracts between [WatchMyCastle](https://github.com/watchmycastle) services: event schemas, transport rules, fixtures and small reference implementations ("oracles") that each service's tests check against. This repository plays the role that `livekit/protocol` plays for LiveKit: one place that defines how services talk to each other.

| Contract | Between | What it defines |
|---|---|---|
| [incident-slice-1](incident-slice-1/) | [camera-event-agent](https://github.com/watchmycastle/camera-event-agent) → [incident-service](https://github.com/watchmycastle/incident-service) | Camera event (observation) format, validation rules, incident state scenarios |
| [incident-slice-2](incident-slice-2/) | same | HTTP transport: delivery, acknowledgements, retries, authentication cases |

Each folder has its own README, fixtures and a `SHA256SUMS` file. The contracts are **frozen**: a change is a new version, agreed in an issue first, because both services must move together.

## Using the contracts in a service's tests

Check this repository out next to the service and put the contract folders on `PYTHONPATH`:

```sh
git clone https://github.com/watchmycastle/contracts.git ../contracts
export PYTHONPATH="../contracts/incident-slice-1:../contracts/incident-slice-2"
```

## Checking the contracts themselves

```sh
cd incident-slice-1 && sha256sum -c SHA256SUMS && python3 -B -m unittest test_contract
cd ../incident-slice-2 && sha256sum -c SHA256SUMS && PYTHONPATH=../incident-slice-1 python3 -B -m unittest test_transport_contract
```

## License

WatchMyCastle is licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE).
