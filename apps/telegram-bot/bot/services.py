import io
import httpx


class APIError(Exception):
    pass


class BoundedBuffer(io.BytesIO):
    def __init__(self, max_bytes):
        super().__init__()
        self.max_bytes = max_bytes

    def write(self, data):
        if self.tell() + len(data) > self.max_bytes:
            raise APIError("Фото тым үлкен")
        return super().write(data)


class Backend:
    def __init__(self, url, key):
        self.client = httpx.AsyncClient(base_url=url.rstrip("/") + "/", headers={"X-Bot-Key": key}, timeout=30)

    async def request(self, method, path, **kwargs):
        try:
            response = await self.client.request(method, path.lstrip("/"), **kwargs)
            if response.status_code in {403, 409, 422, 429}:
                try:
                    detail = response.json().get("detail")
                except ValueError:
                    detail = None
                if isinstance(detail, str):
                    raise APIError(detail)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise APIError("Сұраныс орындалмады. Деректеріңіз сақталды, қайта көріңіз.") from exc

    async def settings(self):
        return await self.request("GET", "settings")

    async def account(self, user_id, identifier, kind="account"):
        return await self.request("POST", "subscribers/lookup", json={
            "telegram_user_id": user_id, "identifier": identifier, "kind": kind,
        })

    async def reading(self, payload):
        return await self.request("POST", "subscribers/readings", json=payload)

    async def readings(self, user_id):
        return await self.request("GET", f"subscribers/{user_id}/readings")

    async def upload(self, bot, telegram_user_id, photo, file_type):
        config = await self.settings()
        max_bytes = config["max_photo_mb"] * 1024 * 1024
        if photo.file_size and photo.file_size > max_bytes:
            raise APIError(f"Фото көлемі {config['max_photo_mb']} МБ-тан аспауы керек.")
        file = await bot.get_file(photo.file_id)
        buffer = BoundedBuffer(max_bytes)
        await bot.download_file(file.file_path, destination=buffer)
        return await self.request(
            "POST",
            "photos",
            data={"telegram_user_id": telegram_user_id, "telegram_file_id": photo.file_id, "file_type": file_type},
            files={"photo": ("photo.jpg", buffer.getvalue(), "image/jpeg")},
        )

    async def create(self, payload):
        return await self.request("POST", "applications", json=payload)

    async def applications(self, user_id, page=1):
        return await self.request("GET", f"users/{user_id}/applications", params={"page": page})

    async def application(self, user_id, application_id):
        return await self.request("GET", f"users/{user_id}/applications/{application_id}")
