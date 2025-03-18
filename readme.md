# VPN Tunnel System with RabbitMQ

[![](https://mermaid.ink/img/pako:eNqNlNtu2kAQhl9ltLlJJEhtAwHcqpLBqIoqUkKIKrWuqsUeg4VPWa-bRklu-wB9xD5Jx1kbG2hp9wov_zf7z2H3kbmJh8xkK8HTNSxsJwZaWb5UGw6zE3eDAq5Q3idiA3rfONcH59q59kq_cJiSF2s-vf7ssDlfLgM5va51hsO-mKYportaa5FynMSSBzGFtmpxBxa3V6Y-NAqwQmUe1-hoBx3VaHcH7fwBHRP64Qbeo4gxhFPrTGk2L9-1zN6Vjf4im5BsgSIKYh5CI5nyYPrHaZw9gXb77ZPDdEiDeAVbm9C-BDKpOewJxg2rpdyAjyKQCJfj6QzmeJdjJiGIZVIkC6e3GYpfP34qq2d7MSx4o4J0iOQezDg1UoIvkkjRCiO-CLNPN-OoMF2wptczmOXLMMjWQBzEaii-CuWsCEFjsDMTJdyDKWYZXyHYGAbfUDwAJUFly_IIRQGOGj0uoYsy-9L5sbztRv9Kug_vkDrC6_Kl4UMja4q0j46qkg1UyeaYpWQRjxbNPjQ-PFYqcnGkULr2z0pZh73R9bJUW8f_OSTVoOlGs0gFWo52oZ8oPcZeNdJuyLPMRh_oWoMfhKF54vvDoaa13CRMhHm_JjOtTIpkg-37wJNr00i_v96DafBLGHW_51eAeaJ1hkvs7cvVDayO0_yu29kSA6Pf1_sHB1ASpd7ru647KO2daC9rS_e8rtYp6AYPVmsE2_dDbY1bNjTfAbU7AXXbWYtRhyIeePSePhYKh8k1Rugwk356XGyKB_OZdDyXyc1D7DJTihxbTCT5as1Mn4cZfeWpR1NrB5ze4Gi7m_L4U5JU38-_Aaw3ub0?type=png)](https://mermaid.live/edit#pako:eNqNlNtu2kAQhl9ltLlJJEhtAwHcqpLBqIoqUkKIKrWuqsUeg4VPWa-bRklu-wB9xD5Jx1kbG2hp9wov_zf7z2H3kbmJh8xkK8HTNSxsJwZaWb5UGw6zE3eDAq5Q3idiA3rfONcH59q59kq_cJiSF2s-vf7ssDlfLgM5va51hsO-mKYportaa5FynMSSBzGFtmpxBxa3V6Y-NAqwQmUe1-hoBx3VaHcH7fwBHRP64Qbeo4gxhFPrTGk2L9-1zN6Vjf4im5BsgSIKYh5CI5nyYPrHaZw9gXb77ZPDdEiDeAVbm9C-BDKpOewJxg2rpdyAjyKQCJfj6QzmeJdjJiGIZVIkC6e3GYpfP34qq2d7MSx4o4J0iOQezDg1UoIvkkjRCiO-CLNPN-OoMF2wptczmOXLMMjWQBzEaii-CuWsCEFjsDMTJdyDKWYZXyHYGAbfUDwAJUFly_IIRQGOGj0uoYsy-9L5sbztRv9Kug_vkDrC6_Kl4UMja4q0j46qkg1UyeaYpWQRjxbNPjQ-PFYqcnGkULr2z0pZh73R9bJUW8f_OSTVoOlGs0gFWo52oZ8oPcZeNdJuyLPMRh_oWoMfhKF54vvDoaa13CRMhHm_JjOtTIpkg-37wJNr00i_v96DafBLGHW_51eAeaJ1hkvs7cvVDayO0_yu29kSA6Pf1_sHB1ASpd7ru647KO2daC9rS_e8rtYp6AYPVmsE2_dDbY1bNjTfAbU7AXXbWYtRhyIeePSePhYKh8k1Rugwk356XGyKB_OZdDyXyc1D7DJTihxbTCT5as1Mn4cZfeWpR1NrB5ze4Gi7m_L4U5JU38-_Aaw3ub0)A container-based VPN system that uses RabbitMQ as a message broker for communication between two containers over TUN devices.

## 🚀 Installation

### Requirements
- Docker 20.10+
- Docker Compose 2.20+

### Start command
```bash
docker compose down -v && docker compose up --build
```

### Logs
```bash
docker compose logs -f
```

### Open RabbitMQ Management
- URL: [http://localhost:15672](http://localhost:15672)
- Username: `admin`
- Password: `admin`


## 📂 Project Structure
```plaintext
.
├── container_a/
│ ├── Dockerfile
│ ├── tun_reader.py
│ └── start.sh
├── container_b/
│ ├── Dockerfile
│ ├── tun_writer.py
│ └── start.sh
├── common.py
├── docker-compose.yml
└── requirements.txt
```

## 🛠️ Configuration

| Komponente         | Container A               | Container B               |
|--------------------|---------------------------|---------------------------|
| **TUN-IP**         | 192.0.2.2/24              | 192.0.2.3/24              |
| **Routing**        | `default via 192.0.2.1`   | `default via 192.0.2.1`   |
| **AMQP Queues**    | Quorum, Durable           | Quorum, Durable           |
| **Healthcheck**    | RabbitMQ Status           | Process Alive Check       |

## 📜 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.



