import { NextRequest, NextResponse } from "next/server";
import { SignJWT, importPKCS8 } from "jose";

const GITHUB_APP_ID = process.env.GITHUB_APP_ID;
const GITHUB_INSTALLATION_ID = process.env.GITHUB_INSTALLATION_ID;
const GITHUB_PRIVATE_KEY = process.env.GITHUB_PRIVATE_KEY;

const REPO_OWNER = "portolan-sdi";
const REPO_NAME = "portolan-registry";

interface SubmitRequest {
  url: string;
}

function deriveSlug(url: string): string {
  try {
    const parsed = new URL(url);
    const pathParts = parsed.pathname.split("/").filter(Boolean);
    const catalogIndex = pathParts.findIndex((p) => p === "catalog.json");
    if (catalogIndex > 0) {
      return pathParts[catalogIndex - 1];
    }
    if (pathParts.length >= 2) {
      return pathParts[pathParts.length - 2];
    }
    return `catalog-${Date.now()}`;
  } catch {
    return `catalog-${Date.now()}`;
  }
}

async function getInstallationToken(): Promise<string> {
  if (!GITHUB_APP_ID || !GITHUB_INSTALLATION_ID || !GITHUB_PRIVATE_KEY) {
    throw new Error("GitHub App credentials not configured");
  }

  const privateKey = await importPKCS8(GITHUB_PRIVATE_KEY, "RS256");

  const now = Math.floor(Date.now() / 1000);
  const jwt = await new SignJWT({})
    .setProtectedHeader({ alg: "RS256" })
    .setIssuedAt(now - 60)
    .setExpirationTime(now + 600)
    .setIssuer(GITHUB_APP_ID)
    .sign(privateKey);

  const res = await fetch(
    `https://api.github.com/app/installations/${GITHUB_INSTALLATION_ID}/access_tokens`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${jwt}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
    }
  );

  if (!res.ok) {
    const error = await res.text();
    throw new Error(`Failed to get installation token: ${error}`);
  }

  const data = await res.json();
  return data.token;
}

export async function POST(req: NextRequest) {
  try {
    const body: SubmitRequest = await req.json();
    const { url } = body;

    if (!url || !url.trim().endsWith("catalog.json")) {
      return NextResponse.json(
        { error: "URL must end with catalog.json" },
        { status: 400 }
      );
    }

    let token: string;
    try {
      token = await getInstallationToken();
    } catch (err) {
      console.error("Auth error:", err);
      return NextResponse.json(
        { error: "Server not configured for submissions" },
        { status: 503 }
      );
    }

    const slug = deriveSlug(url);
    const branchName = `add-${slug}-${Date.now()}`;

    const mainRef = await fetch(
      `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/git/ref/heads/main`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
        },
      }
    );

    if (!mainRef.ok) {
      throw new Error("Failed to get main branch ref");
    }

    const mainData = await mainRef.json();
    const mainSha = mainData.object.sha;

    const createBranch = await fetch(
      `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/git/refs`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
        },
        body: JSON.stringify({
          ref: `refs/heads/${branchName}`,
          sha: mainSha,
        }),
      }
    );

    if (!createBranch.ok) {
      throw new Error("Failed to create branch");
    }

    const yamlContent = `url: ${url}\n`;
    const filePath = `catalogs/${slug}.yaml`;

    const createFile = await fetch(
      `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/${filePath}`,
      {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
        },
        body: JSON.stringify({
          message: `Add catalog: ${slug}`,
          content: Buffer.from(yamlContent).toString("base64"),
          branch: branchName,
        }),
      }
    );

    if (!createFile.ok) {
      throw new Error("Failed to create file");
    }

    const createPr = await fetch(
      `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/pulls`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
        },
        body: JSON.stringify({
          title: `Add catalog: ${slug}`,
          head: branchName,
          base: "main",
          body: `Submitted via portolan.dev\n\nCatalog URL: ${url}`,
        }),
      }
    );

    if (!createPr.ok) {
      const error = await createPr.text();
      throw new Error(`Failed to create PR: ${error}`);
    }

    const prData = await createPr.json();

    return NextResponse.json({
      success: true,
      pr_url: prData.html_url,
      pr_number: prData.number,
    });
  } catch (err) {
    console.error("Submit error:", err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Submission failed" },
      { status: 500 }
    );
  }
}
