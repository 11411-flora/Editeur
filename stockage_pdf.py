import os


class StockageLocal:
    """Pour developper sur ton ordinateur : un simple dossier."""

    def __init__(self, dossier="pdf_cache"):
        self.dossier = dossier
        os.makedirs(dossier, exist_ok=True)

    def _chemin(self, cle):
        return os.path.join(self.dossier, cle.replace("/", "__"))

    def existe(self, cle):
        return os.path.exists(self._chemin(cle))

    def ecrire(self, cle, octets):
        provisoire = self._chemin(cle) + ".tmp"
        with open(provisoire, "wb") as f:
            f.write(octets)
        os.replace(provisoire, self._chemin(cle))   # le fichier apparait d'un coup, jamais a moitie

    def acces(self, cle, nom):
        with open(self._chemin(cle), "rb") as f:
            return ("octets", f.read())


class StockageS3:
    """Pour le serveur AWS : les PDF vont dans un bucket S3 prive.
    Le visiteur telecharge ensuite directement depuis S3, avec un lien presigne."""

    def __init__(self, bucket, region):
        import boto3
        self.bucket = bucket
        self.s3 = boto3.client("s3", region_name=region)

    def existe(self, cle):
        from botocore.exceptions import ClientError
        try:
            self.s3.head_object(Bucket=self.bucket, Key=cle)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def ecrire(self, cle, octets):
        self.s3.put_object(
            Bucket=self.bucket, Key=cle, Body=octets, ContentType="application/pdf"
        )

    def acces(self, cle, nom):
        url = self.s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": cle,
                "ResponseContentType": "application/pdf",
                "ResponseContentDisposition": f'attachment; filename="{nom}"',
            },
            ExpiresIn=300,          # le lien presigne vit 5 minutes
        )
        return ("url", url)


def creer():
    mode = os.environ.get("PDF_BACKEND", "local")
    if mode == "s3":
        return StockageS3(os.environ["PDF_BUCKET"], os.environ["AWS_REGION"])
    if mode == "local":
        return StockageLocal()
    raise RuntimeError("PDF_BACKEND doit valoir 'local' ou 's3'")
