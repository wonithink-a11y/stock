"""oci-object-storage.py — OCI Object Storage용 최소 transport (분봉 OCI 승격 파이프라인)

read-write와 read-only 양쪽에서 재사용한다 - upload-minute-oci.py(VM, Instance
Principal 인증)와 promote-minute-manifest.py(GitHub Actions, API Key 인증)가
이 모듈 하나를 같이 쓴다. 네트워크는 여기 하나로만 나간다(collect-minute-kis.py의
KisTransport와 같은 원칙) - 테스트는 FakeOciTransport로 갈아끼운다.

들어 있지 않은 것: 버킷·Dynamic Group·Policy·IAM 사용자 생성. 전부 OCI 콘솔에서
계정 소유자만 할 수 있다(Claude가 대신 못 한다) - CLAUDE.md의 "OCI Object
Storage" 항목 참고.
"""

import os


class OciTransport:
    """실제 OCI 호출. 이 클래스만 네트워크를 안다."""

    def __init__(self, namespace, bucket, auth="instance_principal", config=None):
        import oci
        if auth == "instance_principal":
            signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
            self.client = oci.object_storage.ObjectStorageClient(
                config={}, signer=signer)
        elif auth == "api_key":
            self.client = oci.object_storage.ObjectStorageClient(config or {})
        else:
            raise ValueError("알 수 없는 auth: " + str(auth))
        self.namespace = namespace
        self.bucket = bucket

    def list_names(self, prefix=None):
        """버킷 안 객체 이름 전부. 페이지네이션을 여기서 흡수한다."""
        names = set()
        start = None
        while True:
            resp = self.client.list_objects(
                self.namespace, self.bucket, prefix=prefix,
                start=start, fields="name")
            for o in resp.data.objects:
                names.add(o.name)
            start = resp.data.next_start_with
            if not start:
                break
        return names

    def put(self, name, data):
        """이미 있으면 IAM이 거부한다(OVERWRITE 미부여, 콘솔에서 의도적으로
        뺐다). 여기서 먼저 존재를 확인하지 않는다 - 확인 후 쓰기는 그 사이의
        경합에서 거짓 안전을 준다. 거부는 그대로 위로 전파한다."""
        self.client.put_object(self.namespace, self.bucket, name, data)

    def get(self, name):
        resp = self.client.get_object(self.namespace, self.bucket, name)
        return resp.data.content


class FakeOciTransport:
    """네트워크 없이 돈다. 존재하는 객체는 dict에, 실제 쓰기는 puts에 기록한다."""

    def __init__(self, existing=None):
        self.objects = dict(existing or {})
        self.puts = []

    def list_names(self, prefix=None):
        return {n for n in self.objects if not prefix or n.startswith(prefix)}

    def put(self, name, data):
        if name in self.objects:
            # 실제 IAM 거부와 같은 모양의 예외 - 재현 테스트가 이걸 잡는다.
            raise RuntimeError("OVERWRITE not permitted (IAM): " + name)
        self.objects[name] = data
        self.puts.append(name)

    def get(self, name):
        if name not in self.objects:
            raise KeyError(name)
        return self.objects[name]


def config_from_env(prefix="OCI_"):
    """Actions의 API Key 인증 설정. 시크릿은 여기서만 읽는다."""
    def need(k):
        v = os.environ.get(prefix + k)
        if not v:
            raise SystemExit("환경변수 없음: " + prefix + k)
        return v
    return {
        "user": need("USER_OCID"),
        "tenancy": need("TENANCY_OCID"),
        "fingerprint": need("FINGERPRINT"),
        "region": need("REGION"),
        "key_content": need("PRIVATE_KEY"),
    }
